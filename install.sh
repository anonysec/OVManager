#!/bin/bash
# OVManager OpenVPN Panel Installer
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

# ═══════════════════════════════════════
#  C O L O R S
# ═══════════════════════════════════════
NC=$'\033[0m'
B=$'\033[1m'
D=$'\033[2m'
WH=$'\033[97m'
GR=$'\033[32m'
RD=$'\033[31m'
YL=$'\033[33m'
BL=$'\033[34m'
CY=$'\033[36m'
GY=$'\033[90m'

# ═══════════════════════════════════════
#  U I   H E L P E R S
# ═══════════════════════════════════════
W=58  # inner width

pad() { printf "%-${W}s" "$1"; }

box_top()    { echo -e "  ${BL}┌$(printf '─%.0s' $(seq 1 $W))┐${NC}"; }
box_mid()    { echo -e "  ${BL}├$(printf '─%.0s' $(seq 1 $W))┤${NC}"; }
box_bot()    { echo -e "  ${BL}└$(printf '─%.0s' $(seq 1 $W))┘${NC}"; }
box_line()   { printf "  ${BL}│${NC} %-$((W-2))s${BL}│${NC}\n" "$1"; }
box_empty()  { echo -e "  ${BL}│${NC}$(printf '%*s' $W '')${BL}│${NC}"; }

title() {
    box_empty
    box_line "  ${B}$1${NC}"
    [[ -n "${2:-}" ]] && box_line "  ${GY}$2${NC}"
    box_empty
}

field() {
    local label="$1" value="$2"
    printf "  ${BL}│${NC}   ${GY}%-14s${NC}%s${BL}│${NC}\n" "$label" "$value"
}

step() {
    printf "  ${BL}│${NC}  %s %-$((W-4))s${BL}│${NC}\n" "$1" "$2"
}

spinner() {
    local msg="$1" pid=$2
    local chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏' i=0
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  ${BL}│${NC}  ${CY}%s${NC} %-$((W-4))s${BL}│${NC}" "${chars:$((i%9)):1}" "$msg"
        sleep 0.1
        ((i++))
    done
    wait "$pid" 2>/dev/null
    local rc=$?
    printf "\r\033[K"
    if [[ $rc -eq 0 ]]; then
        step "${GR}✓${NC}" "$msg"
    else
        step "${RD}✗${NC}" "$msg"
        return 1
    fi
}

prompt_val() {
    local var="$1" label="$2" default="$3" hidden="${4:-}"
    local val=""
    if [[ -t 0 ]]; then
        if [[ "$hidden" == "h" ]]; then
            printf "  ${BL}│${NC}   ${WH}%-14s${NC} ${GY}[${default}]${NC} : " "$label"
            read -rs val; printf "\n"
        else
            printf "  ${BL}│${NC}   ${WH}%-14s${NC} ${GY}[${default}]${NC} : " "$label"
            read -r val
        fi
    fi
    [[ -z "$val" ]] && val="$default"
    eval "$var='$val'"
}

die() { echo -e "\n  ${RD}ERROR:${NC} $1\n"; exit 1; }
trap 'echo -e "\n  ${RD}Interrupted.${NC}"; exit 1' INT TERM

# ═══════════════════════════════════════
#  H E L P / A R G S
# ═══════════════════════════════════════
show_help() {
    cat << 'EOF'
  Usage:
    bash <(curl -Ls https://anonysec.github.io/OVManager/install.sh)
    curl -Ls URL | bash -s -- --port 2095 --path dash

  Flags:
    --port PORT         Panel port (default: 2095)
    --path URLPATH      URL path prefix (default: dash)
    --admin-user USER   Admin username
    --admin-pass PASS   Admin password
    --tls-key PATH      TLS private key
    --tls-cert PATH     TLS certificate
    --docker            Use Docker
    --uninstall         Remove OVManager
    --help              Show this help
EOF
    exit 0
}

PORT="" PATHPREFIX="" ADMIN_USER="" ADMIN_PASS="" TLS_KEY="" TLS_CERT=""
DOCKER_FLAG=0 UNINSTALL=0

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
            --uninstall)  UNINSTALL=1; shift ;;
            --help|-h)    show_help ;;
            *)            die "Unknown option: $1" ;;
        esac
    done
}

# ═══════════════════════════════════════
#  I N T E R A C T I V E   S E T U P
# ═══════════════════════════════════════
interactive_setup() {
    prompt_val PORT       "Port"       "$DEFAULT_PORT"
    prompt_val PATHPREFIX "URL path"   "$DEFAULT_PATH"
    prompt_val ADMIN_USER "Admin user" "$DEFAULT_USER"
    prompt_val ADMIN_PASS "Admin pass" "$DEFAULT_PASS" "h"

    box_mid
    field "Install dir" "$INSTALL_DIR"
    field "Mode"        "$([ $DOCKER_FLAG -eq 1 ] && echo Docker || echo Native-systemd)"
    box_mid

    if [[ -t 0 ]]; then
        printf "  ${BL}│${NC}   Proceed? [${GR}Y${NC}/n] : "
        read -r c; [[ "$c" =~ ^[Nn]$ ]] && die "Cancelled."
    fi
}

# ═══════════════════════════════════════
#  D E P S
# ═══════════════════════════════════════
check_root() {
    [[ "$EUID" -ne 0 ]] && die "Must run as root."
}

check_deps() {
    local missing=()
    for cmd in curl tar openssl git; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        step "${YL}↓${NC}" "Installing: ${missing[*]}"
        apt-get update -qq >/dev/null && apt-get install -y -qq "${missing[@]}" >/dev/null \
            || die "Failed to install: ${missing[*]}"
    fi
    step "${GR}✓${NC}" "Dependencies OK"
}

# ═══════════════════════════════════════
#  I N S T A L L
# ═══════════════════════════════════════
do_install() {
    [[ -d "$INSTALL_DIR" ]] && die "Already installed at $INSTALL_DIR. Use --uninstall first."

    box_empty; box_mid; box_empty
    box_line "  ${B}${WH}Installing${NC}"
    box_empty

    # Source
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

    # Backend
    cd "$INSTALL_DIR"
    uv sync --quiet 2>&1 &
    spinner "Installing Python dependencies" $!

    # Config (before frontend build — Vite needs VITE_URLPATH)
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
    step "${GR}✓${NC}" "Configuration written"

    # Frontend
    if [[ -f "$INSTALL_DIR/frontend/package.json" ]]; then
        cd "$INSTALL_DIR/frontend"
        npm ci --silent >/dev/null 2>&1 &
        spinner "Installing Node.js dependencies" $!
        npm run build --silent >/dev/null 2>&1 &
        spinner "Building frontend assets" $!
    fi

    # Service
    if [[ $DOCKER_FLAG -eq 1 ]]; then
        setup_docker
    else
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
        spinner "Starting service" $!
    fi

    # Done
    box_mid; box_empty
    box_line "  ${GR}${B}✓  INSTALLED${NC}"
    box_empty
    box_line "  ${WH}http://$(hostname -I | awk '{print $1}'):${PORT}/${PATHPREFIX}/${NC}"
    box_line "  ${GY}Login: ${WH}${ADMIN_USER}${NC} / ${WH}${ADMIN_PASS}${NC}"
    box_empty
    box_line "  ${GY}systemctl status ${SYSTEMD_SERVICE}${NC}"
    box_line "  ${GY}systemctl restart ${SYSTEMD_SERVICE}${NC}"
    box_empty
    box_bot
    echo ""
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
    spinner "Starting Docker containers" $!
}

do_update() {
    [[ ! -d "$INSTALL_DIR" ]] && die "Not installed"
    cd "$INSTALL_DIR"
    git pull origin main 2>&1 &
    spinner "Pulling changes" $!
    uv sync --quiet 2>&1 &
    spinner "Updating dependencies" $!
    if [[ -f "frontend/package.json" ]]; then
        cd frontend
        npm ci --silent >/dev/null 2>&1 &
        spinner "Updating frontend" $!
        npm run build --silent >/dev/null 2>&1 &
        spinner "Rebuilding frontend" $!
    fi
    systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 &
    spinner "Restarting service" $!
    box_empty; step "${GR}✓${NC}" "Updated"; box_bot; echo ""
}

do_uninstall() {
    if [[ -t 0 ]]; then
        printf "  Remove ${INSTALL_DIR}? [y/N] : "; read -r c
        [[ ! "$c" =~ ^[Yy]$ ]] && die "Cancelled."
    fi
    systemctl stop "$SYSTEMD_SERVICE" 2>/dev/null
    systemctl disable "$SYSTEMD_SERVICE" 2>/dev/null
    rm -f "/etc/systemd/system/${SYSTEMD_SERVICE}"
    systemctl daemon-reload 2>/dev/null
    rm -rf "$INSTALL_DIR"
    echo -e "  ${GR}✓ Uninstalled${NC}\n"
}

# ═══════════════════════════════════════
#  M A I N
# ═══════════════════════════════════════
main() {
    parse_args "$@"
    clear

    [[ $UNINSTALL -eq 1 ]] && { do_uninstall; exit 0; }

    box_top
    title "OVManager" "OpenVPN Panel Installer  v1.5"

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
        field "Mode"       "$([ $DOCKER_FLAG -eq 1 ] && echo Docker || echo Native-systemd)"
        box_mid
    fi

    check_root
    check_deps
    do_install
}

main "$@"
