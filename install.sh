#!/bin/bash
# OVManager OpenVPN Panel Installer — TUI Edition
# Usage: bash <(curl -Ls https://anonysec.github.io/OVManager/install.sh)
#        curl -Ls URL | bash -s -- --port 2095 --path dash

set -uo pipefail

# ══════════════════════════════════════════════════
#  C O N F I G
# ══════════════════════════════════════════════════
REPO="anonysec/OVManager"
INSTALL_DIR="/opt/ovmanager"
DEFAULT_PORT=2095
DEFAULT_PATH="dash"
DEFAULT_USER="admin"
DEFAULT_PASS="admin"
SYSTEMD_SERVICE="ovmanager.service"

# ══════════════════════════════════════════════════
#  C O L O R S
# ══════════════════════════════════════════════════
C='\033'
R="${C}[0m"
BOLD="${C}[1m"
DIM="${C}[2m"
RED="${C}[31m"
GREEN="${C}[32m"
YELLOW="${C}[33m"
BLUE="${C}[34m"
CYAN="${C}[36m"
WHITE="${C}[97m"
BG_BLUE="${C}[44m"
BG_GREEN="${C}[42m"
BG_RED="${C}[41m"

# ══════════════════════════════════════════════════
#  H E L P E R S
# ══════════════════════════════════════════════════
clear_line() { printf "\r\033[K"; }
spin_chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

spinner() {
    local msg="$1" pid=$2 logfile="${3:-}"
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  ${CYAN}%s${R} %s" "${spin_chars:$((i%10)):1}" "$msg"
        sleep 0.1
        ((i++))
    done
    wait "$pid" 2>/dev/null
    local rc=$?
    clear_line
    if [[ $rc -eq 0 ]]; then
        printf "  ${GREEN}✓${R} %s\n" "$msg"
    else
        printf "  ${RED}✗${R} %s (exit code: %d)\n" "$msg" "$rc"
        return 1
    fi
    return 0
}

step_ok()   { echo -e "  ${GREEN}✓${R} $1"; }
step_warn() { echo -e "  ${YELLOW}⚠${R} $1"; }
step_fail() { echo -e "  ${RED}✗${R} $1"; }
step_info() { echo -e "  ${BLUE}●${R} $1"; }
step_dim()  { echo -e "  ${DIM}$1${R}"; }

box_line() { echo -e "  ${CYAN}│${R} $1"; }

banner() {
    clear
    echo -e ""
    echo -e "  ${BLUE}╔══════════════════════════════════════════════╗${R}"
    echo -e "  ${BLUE}║${R}                                              ${BLUE}║${R}"
    echo -e "  ${BLUE}║${R}  ${BOLD}${WHITE}██╗   ██╗██╗  ███████╗███╗   ███╗ ██████╗ ${R}  ${BLUE}║${R}"
    echo -e "  ${BLUE}║${R}  ${BOLD}${WHITE}██║   ██║██║  ██╔════╝████╗ ████║██╔═══██╗${R}  ${BLUE}║${R}"
    echo -e "  ${BLUE}║${R}  ${BOLD}${WHITE}██║   ██║██║  █████╗  ██╔████╔██║██║   ██║${R}  ${BLUE}║${R}"
    echo -e "  ${BLUE}║${R}  ${BOLD}${WHITE}╚██╗ ██╔╝██║  ██╔══╝  ██║╚██╔╝██║██║   ██║${R}  ${BLUE}║${R}"
    echo -e "  ${BLUE}║${R}  ${BOLD}${WHITE} ╚████╔╝ ██║  ███████╗██║ ╚═╝ ██║╚██████╔╝${R}  ${BLUE}║${R}"
    echo -e "  ${BLUE}║${R}  ${BOLD}${WHITE}  ╚═══╝  ╚═╝  ╚══════╝╚═╝     ╚═╝ ╚═════╝ ${R}  ${BLUE}║${R}"
    echo -e "  ${BLUE}║${R}                                              ${BLUE}║${R}"
    echo -e "  ${BLUE}║${R}  ${DIM}OpenVPN Panel — Free & Open Source${R}          ${BLUE}║${R}"
    echo -e "  ${BLUE}║${R}  ${DIM}https://github.com/anonysec/OVManager${R}      ${BLUE}║${R}"
    echo -e "  ${BLUE}║${R}                                              ${BLUE}║${R}"
    echo -e "  ${BLUE}╚══════════════════════════════════════════════╝${R}"
    echo -e ""
}

divider() {
    printf "  ${DIM}──────────────────────────────────────────────────────────────${R}\n"
}

header() {
    printf "\n  ${BOLD}${BLUE}┌──────────────────────────────────────┐${R}\n"
    printf "  ${BOLD}${BLUE}│${R}  ${BOLD}${WHITE}%-36s${R}  ${BOLD}${BLUE}│${R}\n" "$1"
    printf "  ${BOLD}${BLUE}└──────────────────────────────────────┘${R}\n\n"
}

# ══════════════════════════════════════════════════
#  E R R O R   H A N D L I N G
# ══════════════════════════════════════════════════
die() {
    printf "\n  ${BG_RED}${WHITE}${BOLD} ERROR ${R} %s\n\n" "$1" >&2
    exit 1
}

trap 'die "Installation interrupted by user"' INT TERM

# ══════════════════════════════════════════════════
#  H E L P
# ══════════════════════════════════════════════════
show_help() {
    cat << 'EOF'

  OVManager OpenVPN Panel Installer

  Usage:
    bash <(curl -Ls https://anonysec.github.io/OVManager/install.sh)
    curl -Ls URL | bash -s -- --port 2095 --path dash --admin-user admin --admin-pass secret

  Flags:
    --port PORT         Panel port (default: 2095)
    --path URLPATH      URL path prefix (default: dash)
    --admin-user USER   Admin username (default: admin)
    --admin-pass PASS   Admin password (default: admin)
    --tls-key PATH      TLS private key (optional)
    --tls-cert PATH     TLS certificate (optional)
    --docker            Use Docker instead of native install
    --uninstall         Remove OVManager
    --help              Show this help

EOF
    exit 0
}

# ══════════════════════════════════════════════════
#  P A R S E   A R G S
# ══════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════
#  I N T E R A C T I V E   M E N U
# ══════════════════════════════════════════════════
prompt_value() {
    local var_name="$1" label="$2" default="$3" hidden="${4:-}"
    local val=""
    if [[ -t 0 ]]; then
        if [[ "$hidden" == "hidden" ]]; then
            printf "  ${WHITE}%-18s${R} [${DIM}%s${R}]: " "$label" "$default"
            read -rs val
            printf "\n"
        else
            printf "  ${WHITE}%-18s${R} [${DIM}%s${R}]: " "$label" "$default"
            read -r val
        fi
    fi
    [[ -z "$val" ]] && val="$default"
    eval "$var_name='$val'"
}

prompt_choice() {
    local var_name="$1" label="$2" default="$3"
    shift 3
    local options=("$@")
    if [[ -t 0 ]]; then
        printf "  ${WHITE}%s${R}\n" "$label"
        for i in "${!options[@]}"; do
            local marker=" "
            [[ "${options[$i]}" == "$default" ]] && marker="${GREEN}●${R}"
            printf "    %b %d) %s\n" "$marker" $((i+1)) "${options[$i]}"
        done
        printf "  ${DIM}Press Enter for default [%s]${R}: " "$default"
        read -r choice
        if [[ -z "$choice" ]]; then
            eval "$var_name='$default'"
        elif [[ "$choice" =~ ^[0-9]+$ ]] && [[ "$choice" -ge 1 ]] && [[ "$choice" -le ${#options[@]} ]]; then
            eval "$var_name='${options[$((choice-1))]}'"
        else
            eval "$var_name='$choice'"
        fi
    else
        eval "$var_name='$default'"
    fi
}

interactive_setup() {
    header "Configuration"

    prompt_value PORT "Port" "$DEFAULT_PORT"
    prompt_value PATHPREFIX "URL path" "$DEFAULT_PATH"
    prompt_value ADMIN_USER "Admin user" "$DEFAULT_USER"
    prompt_value ADMIN_PASS "Admin password" "$DEFAULT_PASS" hidden

    divider
    printf "\n  ${BOLD}Summary:${R}\n"
    box_line "Port:        ${CYAN}${PORT}${R}"
    box_line "URL path:    ${CYAN}/${PATHPREFIX}/${R}"
    box_line "Admin user:  ${CYAN}${ADMIN_USER}${R}"
    box_line "Install dir: ${CYAN}${INSTALL_DIR}${R}"
    box_line "Mode:        ${CYAN}$([ $DOCKER_FLAG -eq 1 ] && echo 'Docker' || echo 'Native (systemd)')${R}"
    printf "\n"

    if [[ -t 0 ]]; then
        printf "  ${BOLD}Proceed with installation?${R} [${GREEN}Y${R}/n]: "
        read -r confirm
        if [[ "$confirm" =~ ^[Nn]$ ]]; then
            die "Installation cancelled."
        fi
    fi
}

# ══════════════════════════════════════════════════
#  D E P S
# ══════════════════════════════════════════════════
check_root() {
    [[ "$EUID" -ne 0 ]] && die "Must run as root. Use: sudo bash <(curl -Ls URL)"
}

check_deps() {
    local missing=()
    for cmd in curl tar openssl git; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        step_warn "Installing missing deps: ${missing[*]}"
        apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq "${missing[@]}" >/dev/null 2>&1 \
            || die "Failed to install: ${missing[*]}"
        step_ok "Dependencies installed"
    else
        step_ok "All dependencies found"
    fi
}

# ══════════════════════════════════════════════════
#  I N S T A L L
# ══════════════════════════════════════════════════
do_install() {
    [[ -d "$INSTALL_DIR" ]] && die "Already installed at $INSTALL_DIR. Run with --uninstall first."

    header "Installing OVManager"

    # 1. Source
    step_info "Downloading source..."
    if command -v git >/dev/null 2>&1; then
        git clone --depth 1 --branch main "https://github.com/${REPO}.git" "$INSTALL_DIR" >/dev/null 2>&1 &
        spinner "Cloning repository" $!
    else
        curl -sSLo /tmp/ovmanager.tar.gz "https://github.com/${REPO}/archive/refs/heads/main.tar.gz" >/dev/null 2>&1 &
        spinner "Downloading tarball" $!
        tar -xzf /tmp/ovmanager.tar.gz -C /opt/ 2>/dev/null
        mv "/opt/$(basename ${REPO})-main" "$INSTALL_DIR" 2>/dev/null || \
        mv "/opt/OVManager-main" "$INSTALL_DIR" 2>/dev/null || \
        die "Failed to extract"
        rm -f /tmp/ovmanager.tar.gz
    fi

    # 2. Backend
    step_info "Setting up backend..."
    cd "$INSTALL_DIR"
    uv sync --quiet 2>&1 &
    spinner "Installing Python dependencies" $!

    # 3. Config (before frontend build so Vite picks up VITE_URLPATH)
    step_info "Writing configuration..."
    local jwt_secret
    jwt_secret=$(openssl rand -base64 48 2>/dev/null || head -c 48 /dev/urandom | base64)

    [[ -f "$INSTALL_DIR/.env.example" ]] || die ".env.example not found in repository"
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
    step_ok "Configuration written"

    # 4. Frontend (after config so VITE_URLPATH is available)
    if [[ -f "$INSTALL_DIR/frontend/package.json" ]]; then
        step_info "Building frontend..."
        cd "$INSTALL_DIR/frontend"
        npm ci --silent >/dev/null 2>&1 &
        spinner "Installing Node.js dependencies" $!
        npm run build --silent >/dev/null 2>&1 &
        spinner "Building frontend assets" $!
    fi

    # 5. Service
    if [[ $DOCKER_FLAG -eq 1 ]]; then
        setup_docker
    else
        step_info "Creating systemd service..."
        local real_uv
        real_uv=$(command -v uv)
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
        spinner "Starting ovmanager service" $!
    fi

    # Done
    divider
    printf "\n"
    printf "  ${BG_GREEN}${WHITE}${BOLD}  ✓  INSTALLED SUCCESSFULLY  ${R}\n\n"
    printf "  ${BOLD}Access:${R}  ${CYAN}http://$(hostname -I | awk '{print $1}'):${PORT}/${PATHPREFIX}/${R}\n"
    printf "  ${BOLD}Login:${R}   ${GREEN}${ADMIN_USER}${R} / ${GREEN}${ADMIN_PASS}${R}\n\n"
    printf "  ${DIM}Commands:${R}\n"
    printf "    ${DIM}systemctl status ${SYSTEMD_SERVICE}${R}\n"
    printf "    ${DIM}systemctl restart ${SYSTEMD_SERVICE}${R}\n"
    printf "    ${DIM}journalctl -u ${SYSTEMD_SERVICE} -f${R}\n\n"
}

setup_docker() {
    step_info "Setting up Docker..."
    local compose_file="$INSTALL_DIR/docker-compose.yml"
    local jwt_secret
    jwt_secret=$(openssl rand -base64 48 2>/dev/null)

    cat > "$compose_file" << COMPEOF
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
      - VITE_URLPATH=${PATHPREFIX}
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
COMPEOF

    cd "$INSTALL_DIR"
    if command -v docker compose >/dev/null 2>&1; then
        docker compose up -d 2>&1 &
    elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose up -d 2>&1 &
    else
        die "Docker not found"
    fi
    spinner "Starting Docker containers" $!
}

# ══════════════════════════════════════════════════
#  U P D A T E
# ══════════════════════════════════════════════════
do_update() {
    [[ ! -d "$INSTALL_DIR" ]] && die "Not installed at $INSTALL_DIR"
    header "Updating OVManager"
    cd "$INSTALL_DIR"
    git pull origin main 2>&1 &
    spinner "Pulling latest changes" $!
    uv sync 2>&1 | tail -1 &
    spinner "Updating Python dependencies" $!
    if [[ -f "frontend/package.json" ]]; then
        cd frontend
        npm ci --silent 2>/dev/null &
        spinner "Updating Node.js dependencies" $!
        npm run build --silent 2>/dev/null &
        spinner "Rebuilding frontend" $!
    fi
    systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 &
    spinner "Restarting service" $!
    divider
    printf "  ${BG_GREEN}${WHITE}${BOLD}  ✓  UPDATED  ${R}\n\n"
}

# ══════════════════════════════════════════════════
#  U N I N S T A L L
# ══════════════════════════════════════════════════
do_uninstall() {
    header "Uninstalling OVManager"
    if [[ -t 0 ]]; then
        printf "  ${RED}Remove ${INSTALL_DIR} and stop service?${R} [y/N]: "
        read -r confirm
        [[ ! "$confirm" =~ ^[Yy]$ ]] && die "Cancelled."
    fi
    systemctl stop "$SYSTEMD_SERVICE" 2>/dev/null
    systemctl disable "$SYSTEMD_SERVICE" 2>/dev/null
    rm -f "/etc/systemd/system/${SYSTEMD_SERVICE}"
    systemctl daemon-reload 2>/dev/null
    rm -rf "$INSTALL_DIR"
    step_ok "Service removed"
    step_ok "Installation directory removed"
    divider
    printf "  ${BG_GREEN}${WHITE}${BOLD}  ✓  UNINSTALLED  ${R}\n\n"
}

# ══════════════════════════════════════════════════
#  M A I N
# ══════════════════════════════════════════════════
main() {
    parse_args "$@"
    banner

    if [[ $UNINSTALL -eq 1 ]]; then
        do_uninstall
        exit 0
    fi

    # If no flags provided, run interactive setup
    if [[ -z "$PORT" && -z "$ADMIN_USER" ]]; then
        interactive_setup
    else
        # Fill defaults for any unset values
        : "${PORT:=$DEFAULT_PORT}"
        : "${PATHPREFIX:=$DEFAULT_PATH}"
        : "${ADMIN_USER:=$DEFAULT_USER}"
        : "${ADMIN_PASS:=$DEFAULT_PASS}"
    fi

    check_root
    check_deps
    do_install
}

main "$@"
