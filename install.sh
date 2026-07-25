#!/bash
# OVManager OpenVPN Panel Installer
# Supports: native install, docker compose, update, uninstall
# Usage: curl -sSL https://anonysec.github.io/OVManager/install.sh | bash
#        curl -sSL URL | bash -s -- --port 2095 --path dash --tls-key /path/key --tls-cert /path/cert

set -euo pipefail

# ———————— Defaults ————————
REPO="anonysec/OVManager"
INSTALL_DIR="/opt/ovmanager"
DEFAULT_PORT=2095
DEFAULT_PATH="dash"
DOCKER_COMPOSE_FILE="docker-compose.yml"
SYSTEMD_SERVICE="ovmanager.service"
FRONTEND_DIR="frontend"

# ———————— Color definitions ————————
GREEN=$(tput setaf 2 2>/dev/null || echo '\033[32m')
RED=$(tput setaf 1 2>/dev/null || echo '\033[31m')
YELLOW=$(tput setaf 3 2>/dev/null || echo '\033[33m')
BLUE=$(tput setaf 4 2>/dev/null || echo '\033[34m')
NC=$(tput sgr0 2>/dev/null || echo '\033[0m')
BOLD=$(tput bold 2>/dev/null || echo '\033[1m')

# ———————— Logging helpers ————————
log()   { echo -e "  [${GREEN}✓${NC}] $1" ;}
log_y() { echo -e "  [${YELLOW}⚠${NC}] $1" ;}
log_r() { echo -e "  [${RED}✗${NC}] $1" ;}
log_b() { echo -e "  [${BLUE}ℹ${NC}] $1" ; }

# ———————— Error handling ————————
error_exit() {
    log_r "ERROR: $1"
    exit 1
}

trap 'error_exit "Installation interrupted."' INT TERM

# ———————— Help ————————
show_help() {
    cat << EOF
OVManager OpenVPN Panel Installer

Usage: $0 [OPTIONS]

Options:
  --port PORT         Panel port (default: ${DEFAULT_PORT})
  --path URLPATH      URL path prefix (default: ${DEFAULT_PATH})
  --admin-user USER   Admin username (prompted if not provided)
  --admin-pass PASS   Admin password (prompted if not provided)
  --tls-key PATH      Path to TLS private key (optional)
  --tls-cert PATH     Path to TLS certificate (optional)
  --docker            Use docker-compose instead of native install
  --help              Show this help

Env vars (used if flags not provided):
  PANEL_PORT, PANEL_PATH, ADMIN_USER, ADMIN_PASS, SSL_KEYFILE, SSL_CERTFILE

Examples:
  curl -sSL https://anonysec.github.io/OVManager/install.sh | bash
  curl -sSL URL | bash -s -- --port 2095 --path dash
  curl -sSL URL | bash -s -- --admin-user admin --admin-pass secret --docker
EOF
}

# ———————— Parse arguments ————————
parse_args() {
    PORT=""; PATHPREFIX=""; ADMIN_USER=""; ADMIN_PASS=""; TLS_KEY=""; TLS_CERT=""; DOCKER_FLAG=0
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --port)      PORT="$2"; shift 2 ;;
            --path)      PATHPREFIX="$2"; shift 2 ;;
            --admin-user)ADMIN_USER="$2"; shift 2 ;;
            --admin-pass)ADMIN_PASS="$2"; shift 2 ;;
            --tls-key)   TLS_KEY="$2"; shift 2 ;;
            --tls-cert)  TLS_CERT="$2"; shift 2 ;;
            --docker)    DOCKER_FLAG=1; shift ;;
            --help)      show_help; exit 0 ;;
            *)           error_exit "Unknown option: $1" ;;
        esac
    done
}

# ———————— Interactive prompts ————————
prompt_input() {
    local var_name="$1" prompt="$2" default="$3"
    local input=""
    if [[ -t 0 ]]; then
        read -r -p "$prompt [$default]: " input 2>/dev/null || true
    fi
    if [[ -z "$input" ]]; then
        eval "$var_name='$default'"
    else
        eval "$var_name='$input'"
    fi
}

read_config() {
    # Use provided flags first, then env vars, then defaults
    : "${PORT:=${PANEL_PORT:-}}"
    : "${PATHPREFIX:=${PANEL_PATH:-}}"
    : "${ADMIN_USER:=${ADMIN_USER:-}}"
    : "${ADMIN_PASS:=${ADMIN_PASS:-}}"
    : "${TLS_KEY:=${SSL_KEYFILE:-}}"
    : "${TLS_CERT:=${SSL_CERTFILE:-}}"

    [[ -z "$PORT" ]]       && prompt_input PORT       "Port"              "$DEFAULT_PORT"
    [[ -z "$PATHPREFIX" ]] && prompt_input PATHPREFIX "URL path prefix" "$DEFAULT_PATH"
    [[ -z "$ADMIN_USER" ]] && prompt_input ADMIN_USER "Admin username"   "admin"
    [[ -z "$ADMIN_PASS" ]] && prompt_input ADMIN_PASS "Admin password"   "CHANGE_ME" # intentionally insecure for prompt flow
}

# ———————— Dependency checks ————————
check_deps() {
    local missing=()
    for cmd in curl tar systemctl openssl; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_y "Missing dependencies: ${missing[*]}"
        if [[ -t 0 ]]; then
            read -r -p "Attempt to install missing deps with apt-get? [y/N] " resp
        else
            resp="y"
        fi
        if [[ "$resp" =~ ^[Yy]$ ]]; then
            apt-get update -qq && apt-get install -y -qq "${missing[@]}" 2>/dev/null || error_exit "Failed to install dependencies"
            log "Installed missing dependencies"
        else
            error_exit "Required tools missing: ${missing[*]}"
        fi
    fi
}

# ———————— Verify prerequisites ————————
verify_prereqs() {
    if [[ "$EUID" -ne 0 ]]; then error_exit "This script must be run as root. Use sudo."; fi
    command -v systemctl >/dev/null || error_exit "systemctl not found. This script requires systemd."
    if [[ $DOCKER_FLAG -eq 1 ]]; then
        command -v docker >/dev/null 2>&1 || error_exit "docker not found. Install docker first."
    fi
    if [[ -d "$INSTALL_DIR" ]]; then error_exit "Installation directory $INSTALL_DIR already exists. Remove it first."; fi
}

# ———————— Download / clone repo ————————
get_source() {
    log_b "Preparing source..."
    local repo_url="https://github.com/${REPO}.git"
    
    if command -v git >/dev/null 2>&1; then
        log "Cloning repository..."
        git clone --depth 1 --branch main "$repo_url" "$INSTALL_DIR" 2>/dev/null || \
        git clone --depth 1 "$repo_url" "$INSTALL_DIR" || error_exit "Failed to clone repository"
    elif [[ -f /tmp/ovmanager.tar.gz ]]; then
        log "Using cached tarball..."
        tar -xzf /tmp/ovmanager.tar.gz -C /opt/ || error_exit "Failed to extract tarball"
        mv /opt/OVManager "$INSTALL_DIR" || error_exit "Failed to move extracted files"
    else
        log "Downloading repository tarball..."
        curl -sSLo /tmp/ovmanager.tar.gz "https://github.com/${REPO}/archive/refs/heads/main.tar.gz" || \
        curl -sSLo /tmp/ovmanager.tar.gz "https://api.github.com/repos/${REPO}/tarball/" || \
        error_exit "Failed to download repository"
        tar -xzf /tmp/ovmanager.tar.gz -C /opt/ || error_exit "Failed to extract tarball"
        # Find the extracted directory
        local extracted_dir
        extracted_dir=$(ls -d /opt/$(basename ${REPO})-*) || error_exit "Could not find extracted directory"
        mv "$extracted_dir" "$INSTALL_DIR" || error_exit "Failed to move extracted files"
    fi
    log "Source ready at $INSTALL_DIR"
}

# ———————— Setup Python/uv ————————
setup_backend() {
    log_b "Setting up backend..."
    local VENV_DIR="$INSTALL_DIR/.venv"
    
    if command -v python3 >/dev/null 2>&1; then
        log "Using system python3"
    elif command -v python >/dev/null 2>&1 && python --version 2>&1 | grep -q "Python 3"; then
        ln -sf $(command -v python) /usr/local/bin/python3 2>/dev/null || true
    else
        error_exit "python3 not found. Please install python3."
    fi

    # Install uv if not present
    if ! command -v uv >/dev/null 2>&1; then
        log "Installing uv..."
        python3 -m pip install --quiet --upgrade pip 2>/dev/null || \
        python -m pip install --quiet --upgrade pip 2>/dev/null || true
        python3 -m pip install --quiet uv 2>/dev/null || \
        python -m pip install --quiet uv 2>/dev/null || \
        error_exit "Failed to install uv. Install manually or ensure pip can install packages."
    fi

    log "Setting up virtual environment..."
    cd "$INSTALL_DIR" && uv sync || error_exit "uv sync failed"
    log "Backend setup complete"
}

# ———————— Setup frontend ————————
setup_frontend() {
    log_b "Setting up frontend..."
    
    if [[ ! -f "$INSTALL_DIR/$FRONTEND_DIR/package.json" ]]; then
        log_y "No package.json found in frontend/ - skipping frontend install"
        return 0
    fi

    # Try npm
    if command -v npm >/dev/null 2>&1; then
        log "Running npm ci in frontend..."
        cd "$INSTALL_DIR/$FRONTEND_DIR" && npm ci 2>/dev/null && npm run build 2>/dev/null && log "Frontend build complete" || log_y "Frontend build may have warnings"
    # Try npx
    elif command -v npx >/dev/null 2>&1; then
        log "Running npx npm ci in frontend..."
        cd "$INSTALL_DIR/$FRONTEND_DIR" && npx npm ci 2>/dev/null && npx npm run build 2>/dev/null && log "Frontend build complete" || log_y "Frontend build may have warnings"
    else
        log_y "npm not found, skipping frontend build"
    fi
}

# ———————— Write .env ————————
write_env() {
    log_b "Writing configuration..."
    local env_file="$INSTALL_DIR/.env"
    local jwt_secret
    jwt_secret=$(openssl rand -base64 48 2>/dev/null || head -c 48 /dev/urandom | base64)

    [[ -f "$INSTALL_DIR/.env.example" ]] || error_exit ".env.example not found in repository"

    cat "$INSTALL_DIR/.env.example" | sed \
        -e "s|^APP_ENV=.*|APP_ENV=production|" \
        -e "s|^APP_DEBUG=.*|APP_DEBUG=false|" \
        -e "s|^DB_HOST=.*|DB_HOST=127.0.0.1|" \
        -e "s|^DB_DATABASE=.*|DB_DATABASE=ovmanager|" \
        -e "s|^DB_USERNAME=.*|DB_USERNAME=ovmanager|" \
        -e "s|^DB_PASSWORD=.*|DB_PASSWORD=ovmanager|" \
        -e "s|^PORT=.*|PORT=$PORT|" \
        -e "s|^URLPATH=.*|URLPATH=$PATHPREFIX|" \
        -e "s|^ADMIN_USERNAME=.*|ADMIN_USERNAME=$ADMIN_USER|" \
        -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$ADMIN_PASS|" \
        -e "s|^VITE_URLPATH=.*|VITE_URLPATH=$PATHPREFIX|" \
        -e "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$jwt_secret|" \
        -e "s|^HOST=.*|HOST=0.0.0.0|" \
        > "$env_file"

    # Override with TLS if provided
    if [[ -n "$TLS_KEY" && -f "$TLS_KEY" ]]; then
        echo "SSL_KEYFILE=$TLS_KEY" >>"$env_file"
    fi
    if [[ -n "$TLS_CERT" && -f "$TLS_CERT" ]]; then
        echo "SSL_CERTFILE=$TLS_CERT" >>"$env_file"
    fi

    log "Configuration written to $env_file"
    log_b "Generated JWT_SECRET_KEY"
}

# ———————— Systemd service ————————
setup_systemd() {
    log_b "Creating systemd service..."
    local service_file="/etc/systemd/system/$SYSTEMD_SERVICE"
    local real_uv
    real_uv=$(command -v uv || echo "/usr/local/bin/uv")
    
    cat >"$service_file" << EOF
[Unit]
Description=OVManager OpenVPN Panel
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=$real_uv run main.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SYSTEMD_SERVICE" || error_exit "Failed to enable service"
    systemctl restart "$SYSTEMD_SERVICE" || error_exit "Failed to start service"
    log "Systemd service $SYSTEMD_SERVICE configured and running"
}

# ———————— Docker compose ————————
setup_docker() {
    log_b "Generating docker-compose configuration..."
    local compose_file="$INSTALL_DIR/$DOCKER_COMPOSE_FILE"
    
    # Generate TLS config lines
    local tls_config=""
    if [[ -n "$TLS_KEY" && -f "$TLS_KEY" ]]; then
        tls_config="    - ${TLS_KEY}:/run/secrets/server.key\n"
    fi
    if [[ -n "$TLS_CERT" && -f "$TLS_CERT" ]]; then
        tls_config+="    - ${TLS_CERT}:/run/secrets/server.crt\n"
    fi

    cat > "$compose_file" << EOF
version: '3.8'
services:
  ovmanager:
    image: ghcr.io/anonysec/ovmanager:latest
    container_name: ovmanager
    restart: unless-stopped
    ports:
      - "${PORT}:${PORT}"
    environment:
$(printf '      %s\n' \
        "APP_ENV: production" \
        "APP_DEBUG: false" \
        "DB_HOST: db" \
        "DB_DATABASE: ovmanager" \
        "DB_USERNAME: ovmanager" \
        "DB_PASSWORD: ovmanager" \
        "PORT: ${PORT}" \
        "URLPATH: ${PATHPREFIX}" \
        "ADMIN_USERNAME: ${ADMIN_USER}" \
        "ADMIN_PASSWORD: ${ADMIN_PASS}" \
        "VITE_URLPATH: /${PATHPREFIX}/" \
        "JWT_SECRET_KEY: $(openssl rand -base64 48 2>/dev/null || head -c 48 /dev/urandom | base64)")
$( [[ -n "$tls_config" ]] && printf '      TLS_KEY_FILE: /run/secrets/server.key\n      TLS_CERT_FILE: /run/secrets/server.crt\n' )
    volumes:
$( [[ -n "$TLS_KEY" ]] && printf '      - ./server.key:/run/secrets/server.key:ro\n' )
$( [[ -n "$TLS_CERT" ]] && printf '      - ./server.crt:/run/secrets/server.crt:ro\n' )
      - ./backend:/app
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
  ovmanager:
    driver: bridge

volumes:
  db_data:
EOF

    if command -v docker-compose >/dev/null 2>&1; then
        cd "$INSTALL_DIR" && docker-compose up -d || error_exit "Docker compose failed"
    elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        cd "$INSTALL_DIR" && docker compose up -d || error_exit "Docker compose failed"
    else
        error_exit "Neither docker-compose nor docker compose found"
    fi
    log "Docker compose deployment started"
}

# ———————— Update ————————
do_update() {
    log_b "Checking for updates..."
    [[ ! -d "$INSTALL_DIR" ]] && error_exit "Not installed at $INSTALL_DIR"
    log "Pulling latest changes..."
    cd "$INSTALL_DIR" && git pull origin main || error_exit "Git pull failed"
    setup_backend
    setup_frontend
    systemctl restart "$SYSTEMD_SERVICE" || error_exit "Failed to restart service"
    log "Update complete"
}

# ———————— Uninstall ————————
do_uninstall() {
    log_b "Starting uninstall..."
    read -r -p "Remove installation directory $INSTALL_DIR? [y/N] " resp
    [[ "$resp" =~ ^[Yy]$ ]] && rm -rf "$INSTALL_DIR" && log "Removed $INSTALL_DIR"
    read -r -p "Stop and remove systemd service? [y/N] " resp
    if [[ "$resp" =~ ^[Yy]$ ]]; then
        systemctl stop "$SYSTEMD_SERVICE" 2>/dev/null || true
        systemctl disable "$SYSTEMD_SERVICE" 2>/dev/null || true
        rm -f "/etc/systemd/system/$SYSTEMD_SERVICE"
        systemctl daemon-reload
        log "Service removed"
    fi
    log "Uninstall complete"
}

# ———————— Main ————————
main() {
    # Check for subcommands
    if [[ "${1:-}" == "update" ]]; then
        parse_args "$@"
        verify_prereqs
        do_update
        exit 0
    elif [[ "${1:-}" == "uninstall" ]]; then
        parse_args "$@"
        do_uninstall
        exit 0
    fi

    parse_args "$@"

    log_b "${BOLD}══════════════════════════════════${NC}"
    log_b " ${BOLD}O  V  M  A  N  A  G  E  R${NC}  OpenVPN Panel Installer"
    log_b "══════════════════════════════════${NC}"

    # Check for help or no args
    if [[ $# -eq 0 ]]; then
        read_config
    fi

    check_deps
    verify_prereqs

    log "Installing OVManager to $INSTALL_DIR"
    get_source

    setup_backend
    setup_frontend
    write_env

    if [[ $DOCKER_FLAG -eq 1 ]]; then
        setup_docker
    else
        setup_systemd
    fi

    log_b "══════════════════════════════════════════════════════════${NC}"
    if [[ $DOCKER_FLAG -eq 1 ]]; then
        log_b " ${GREEN}✓${NC} OVManager is running via Docker Compose"
        log_b "   Access URL: https://localhost:$PORT/$PATHPREFIX/"
    else
        log_b " ${GREEN}✓${NC} OVManager is running via systemd"
        log_b "   Access URL: http://localhost:$PORT/$PATHPREFIX/"
    fi
    log_b " Default credentials: $ADMIN_USER / $ADMIN_PASS"
    log_b "══════════════════════════════════════════════════════════${NC}"
}

main "$@"