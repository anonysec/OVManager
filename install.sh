#!/bin/bash
# OVManager — OpenVPN Panel Installer
# Usage: bash <(curl -Ls https://anonysec.github.io/OVManager/install.sh)
#        bash <(curl -Ls URL) update
#        bash <(curl -Ls URL) uninstall

set -uo pipefail

# ═══════════════════════════════════════
#  C O N F I G
# ═══════════════════════════════════════
REPO="anonysec/OVManager"
INSTALL_DIR="/opt/ovmanager"
DATA_DIR="/var/lib/ovmanager"
DEFAULT_PORT=2095
DEFAULT_PATH=""
DEFAULT_USER="admin"
DEFAULT_PASS="admin"
SYSTEMD_SERVICE="ovmanager.service"
VERSION="1.6"

# ═══════════════════════════════════════
#  C O L O R S
# ═══════════════════════════════════════
NC=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'
WH=$'\033[97m'; GR=$'\033[32m'; RD=$'\033[31m'
YL=$'\033[33m'; BL=$'\033[34m'; CY=$'\033[36m'; GY=$'\033[90m'

# ═══════════════════════════════════════
#  U I
# ═══════════════════════════════════════
line()   { echo -e "  $1" >&2; }
step()   { line "${GR}  ✓${NC} $1"; }
info()   { line "${CY}  →${NC} $1"; }
warn()   { line "${YL}  ⚠${NC} $1"; }
field()  { printf "  ${GY}%-16s${NC} %s\n" "$1" "$2"; }
sep()    { line "${GY}$(printf '%.0s─' {1..52})${NC}"; }

spinner() {
    local msg="$1" pid=$2 chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏' i=0
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  ${CY}%s${NC} %-48s" "${chars:$((i%9)):1}" "$msg" >&2
        sleep 0.1; ((i++))
    done
    wait "$pid" 2>/dev/null
    local rc=$?
    printf "\r\033[K" >&2
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
    --path URLPATH      URL path prefix (default: root/empty)
    --admin-user USER   Admin username
    --admin-pass PASS   Admin password
    --tls METHOD        TLS method: le, le-ip, self, custom, none (default: le-ip)
    --tls-domain DOM    Domain for Let's Encrypt
    --tls-key KEY       Path to existing TLS key
    --tls-cert CERT     Path to existing TLS cert
    --docker            Use Docker
    --help              Show this help
EOF
    exit 0
}

PORT="" PATHPREFIX="" ADMIN_USER="" ADMIN_PASS="" TLS_MODE="" TLS_DOMAIN="" TLS_KEY="" TLS_CERT=""
DOCKER_FLAG=0 ACTION="install"

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --port)       PORT="$2"; shift 2 ;;
            --path)       PATHPREFIX="$(echo "$2" | sed 's|^/\+||; s|/\+$||')"; shift 2 ;;
            --admin-user) ADMIN_USER="$2"; shift 2 ;;
            --admin-pass) ADMIN_PASS="$2"; shift 2 ;;
            --tls-le)     TLS_MODE="le"; TLS_DOMAIN="$2"; shift 2 ;;
            --tls-ip)     TLS_MODE="le-ip"; TLS_DOMAIN="$(hostname -I | awk '{print $1}')"; shift ;;
            --tls)        TLS_MODE="$2"; shift 2 ;;
            --tls-self)   TLS_MODE="self"; shift ;;
            --tls-custom) TLS_MODE="custom"; TLS_KEY="$2"; TLS_CERT="$3"; shift 3 ;;
            --tls-none)   TLS_MODE="none"; shift ;;
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
#  P O R T   C H E C K
# ═══════════════════════════════════════
port_in_use() {
    ss -ltn 2>/dev/null | awk -v p=":${1}$" '$4 ~ p {exit 0} END {exit 1}'
}

check_port_available() {
    if port_in_use "$1"; then
        die "Port $1 is already in use. Please free port $1 or choose a different port."
    fi
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
    if [[ -t 0 ]]; then
        printf "  TLS mode\n"
        line "  1)  Let's Encrypt (domain)"
        line "  2)  Let's Encrypt (IP)"
        line "  3)  Self-signed cert"
        line "  4)  Custom cert path"
        line "  5)  None (HTTP)"
        printf "  Select [${GR}2${NC}] : "
        read -r tls_choice
        : "${tls_choice:=2}"
        case "$tls_choice" in
            1) TLS_MODE="le" ;;
            2) TLS_MODE="le-ip" ;;
            3) TLS_MODE="self" ;;
            4) TLS_MODE="custom" ;;
            5) TLS_MODE="none" ;;
            *) TLS_MODE="none" ;;
        esac
    fi
    if [[ "$TLS_MODE" == "le" ]]; then
        # Domain only — must enter
        while [[ -z "$TLS_DOMAIN" ]]; do
            if [[ -t 0 ]]; then
                printf "  ${WH}Domain${NC} [${GY}example.com${NC}] : "
                read -r TLS_DOMAIN
            else
                die "Domain is required for Let's Encrypt (use --tls-le DOMAIN)"
            fi
        done
    elif [[ "$TLS_MODE" == "le-ip" ]]; then
        # Show real IP, user can override or press Enter
        local real_ip=$(hostname -I | awk '{print $1}')
        if [[ -z "$TLS_DOMAIN" ]]; then
            if [[ -t 0 ]]; then
                printf "  ${WH}IP${NC} [${GR}%s${NC}] : " "$real_ip"
                read -r TLS_DOMAIN
            fi
            [[ -z "$TLS_DOMAIN" ]] && TLS_DOMAIN="$real_ip"
        fi
    fi
    # Install mode
    if [[ $DOCKER_FLAG -eq 0 && -t 0 ]]; then
        line "  Install mode"
        line "  ${WH}1${NC})  Native (systemd)"
        line "  ${WH}2${NC})  Docker"
        printf "  Select [${GR}1${NC}] : "
        read -r mode_choice
        : "${mode_choice:=1}"
        [[ "$mode_choice" == "2" ]] && DOCKER_FLAG=1
    fi
    local server_ip=$(hostname -I | awk '{print $1}')
    sep
    field "Server IP"     "$server_ip"
    field "Install dir"  "$INSTALL_DIR"
    field "Data dir"     "$DATA_DIR"
    field "Install mode" "$([ $DOCKER_FLAG -eq 1 ] && echo Docker || echo Native)"
    if [[ "$TLS_MODE" == "le" ]]; then
        field "TLS domain" "$TLS_DOMAIN"
    elif [[ "$TLS_MODE" == "le-ip" ]]; then
        field "TLS IP"     "$TLS_DOMAIN"
    fi
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
#  L E T ' S   E N C R Y P T
# ═══════════════════════════════════════
generate_self_signed() {
    info "Generating self-signed certificate..."
    mkdir -p /etc/ssl/self-signed
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout /etc/ssl/self-signed/privkey.pem \
        -out /etc/ssl/self-signed/fullchain.pem \
        -subj "/C=US/ST=Local/L=Local/O=OVManager/CN=$(hostname -I | awk '{print $1}')" 2>/dev/null
    TLS_KEY="/etc/ssl/self-signed/privkey.pem"
    TLS_CERT="/etc/ssl/self-signed/fullchain.pem"
    step "Self-signed certificate generated"
}

get_acme_email() {
    local email="acme-$(openssl rand -hex 4)@example.com"
    echo "$email"
}

install_acme() {
    if [[ ! -x "$HOME/.acme.sh/acme.sh" ]]; then
        info "Installing acme.sh..."
        curl -s https://get.acme.sh | sh
    fi
    source "$HOME/.acme.sh/acme.sh.env"
}

issue_lets_encrypt() {
    local domain="$1" is_ip="$2"
    install_acme
    local email=$(get_acme_email)
    local outdir="/etc/letsencrypt/$domain"
    mkdir -p "$outdir"

    # Check if valid cert already exists
    if [[ -f "$outdir/fullchain.pem" ]]; then
        local expiry=$(openssl x509 -enddate -noout -in "$outdir/fullchain.pem" 2>/dev/null | cut -d= -f2)
        local expiry_epoch=$(date -d "$expiry" +%s 2>/dev/null)
        local now_epoch=$(date +%s)
        local days_left=$(( (expiry_epoch - now_epoch) / 86400 ))
        if [[ $days_left -gt 7 ]]; then
            step "Existing certificate valid for $days_left more days ($outdir)"
            return 0
        fi
        warn "Certificate expires in $days_left days — renewing..."
    fi

    local extra_args=""
    if [[ "$is_ip" == "1" ]]; then
        info "Issuing short-lived certificate for IP $domain (6 days)..."
        extra_args="--certificate-profile shortlived --days 6"
    else
        info "Issuing certificate for domain $domain..."
    fi

    # Issue cert
    ~/.acme.sh/acme.sh \
        --issue -d "$domain" \
        --standalone \
        $extra_args \
        --accountemail "$email" 2>&1 | grep -E "Cert success|Error|error" || die "Failed to issue Let's Encrypt certificate for $domain"

    # Install cert to target directory (no-op reload — service not created yet)
    ~/.acme.sh/acme.sh \
        --install-cert -d "$domain" \
        --key-file "$outdir/privkey.pem" \
        --fullchain-file "$outdir/fullchain.pem" \
        --reloadcmd "true" 2>&1 | tail -3 || die "Failed to install certificate to $outdir"

    step "Certificate installed to $outdir"
}

# ═══════════════════════════════════════
#  I N S T A L L
# ═══════════════════════════════════════
do_install() {
    [[ -d "$INSTALL_DIR" ]] && die "Already installed. Use --uninstall first."
    [[ -d "$DATA_DIR" ]] || mkdir -p "$DATA_DIR"

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
        -e "s|^HOST=.*|HOST=0.0.0.0|" \
        -e "s|^URLPATH=.*|URLPATH=${PATHPREFIX}|" \
        -e "s|^PORT=.*|PORT=${PORT}|" \
        "$INSTALL_DIR/.env.example" > "$INSTALL_DIR/.env"
    # Required vars are commented out in .env.example — write them active (leading blank line)
    printf "\n" >> "$INSTALL_DIR/.env"
    cat >> "$INSTALL_DIR/.env" << EOF
ADMIN_USERNAME=${ADMIN_USER}
ADMIN_PASSWORD=${ADMIN_PASS}
JWT_SECRET_KEY=${jwt_secret}
JWT_ACCESS_TOKEN_EXPIRES=1800
JWT_REFRESH_TOKEN_EXPIRES=604800
EOF
    
    # TLS configuration
    case "$TLS_MODE" in
        le)
            check_port_available 80
            issue_lets_encrypt "$TLS_DOMAIN" "0"
            echo "SSL_KEYFILE=\"/etc/letsencrypt/$TLS_DOMAIN/privkey.pem\"" >> "$INSTALL_DIR/.env"
            echo "SSL_CERTFILE=\"/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem\"" >> "$INSTALL_DIR/.env"
            ;;
        le-ip)
            check_port_available 80
            issue_lets_encrypt "$TLS_DOMAIN" "1"
            echo "SSL_KEYFILE=\"/etc/letsencrypt/$TLS_DOMAIN/privkey.pem\"" >> "$INSTALL_DIR/.env"
            echo "SSL_CERTFILE=\"/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem\"" >> "$INSTALL_DIR/.env"
            ;;
        self)
            generate_self_signed
            echo "SSL_KEYFILE=\"$TLS_KEY\"" >> "$INSTALL_DIR/.env"
            echo "SSL_CERTFILE=\"$TLS_CERT\"" >> "$INSTALL_DIR/.env"
            ;;
        custom)
            [[ -f "$TLS_KEY" && -f "$TLS_CERT" ]] || die "Custom cert/key files not found"
            mkdir -p /etc/letsencrypt/"$TLS_DOMAIN"
            cp "$TLS_KEY" /etc/letsencrypt/"$TLS_DOMAIN"/privkey.pem
            cp "$TLS_CERT" /etc/letsencrypt/"$TLS_DOMAIN"/fullchain.pem
            echo "SSL_KEYFILE=\"/etc/letsencrypt/$TLS_DOMAIN/privkey.pem\"" >> "$INSTALL_DIR/.env"
            echo "SSL_CERTFILE=\"/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem\"" >> "$INSTALL_DIR/.env"
            ;;
        none)
            # No TLS variables set
            ;;
    esac

    if [[ -f "$INSTALL_DIR/frontend/package.json" ]]; then
        info "Building frontend..."
        cd "$INSTALL_DIR/frontend"
        npm ci --silent >/dev/null 2>&1 &
        spinner "Node.js dependencies installed" $!
        npm run build --silent >/dev/null 2>&1 &
        spinner "Frontend built" $!
    fi

    if [[ $DOCKER_FLAG -eq 1 ]]; then
        setup_docker
    else
        info "Setting up systemd service..."
        local real_uv; real_uv=$(command -v uv)
        local start_after="multi-user.target"
        cat > "/etc/systemd/system/${SYSTEMD_SERVICE}" << SVCEOF
[Unit]
Description=OVManager OpenVPN Panel
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="DATA_DIR=${DATA_DIR}"
ExecStart=${real_uv} run main.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
SVCEOF
        # Also write env file for systemd
        echo "DATA_DIR=${DATA_DIR}" >> "$INSTALL_DIR/.env"
        systemctl daemon-reload >/dev/null 2>&1
        systemctl enable "$SYSTEMD_SERVICE" >/dev/null 2>&1
        systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 &
        spinner "Service started" $!

        # Update acme.sh reloadcmd now that service exists
        if [[ "$TLS_MODE" == "le" || "$TLS_MODE" == "le-ip" ]] && [[ -n "$TLS_DOMAIN" ]]; then
            ~/.acme.sh/acme.sh --install-cert -d "$TLS_DOMAIN" \
                --key-file "/etc/letsencrypt/$TLS_DOMAIN/privkey.pem" \
                --fullchain-file "/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem" \
                --reloadcmd "systemctl restart ovmanager.service" >/dev/null 2>&1
        fi
    fi

    sep
    line ""
    step "${B}Installation complete!${NC}"
    line ""
    if [[ "$TLS_MODE" != "none" ]]; then
        if [[ -n "$PATHPREFIX" ]]; then
            line "  ${WH}Access:${NC}  https://$(hostname -I | awk '{print $1}'):${PORT}/${PATHPREFIX}/"
        else
            line "  ${WH}Access:${NC}  https://$(hostname -I | awk '{print $1}'):${PORT}/"
        fi
    else
        if [[ -n "$PATHPREFIX" ]]; then
            line "  ${WH}Access:${NC}  http://$(hostname -I | awk '{print $1}'):${PORT}/${PATHPREFIX}/"
        else
            line "  ${WH}Access:${NC}  http://$(hostname -I | awk '{print $1}'):${PORT}/"
        fi
    fi
    line "  ${WH}Login:${NC}   ${GR}${ADMIN_USER}${NC} / ${GR}${ADMIN_PASS}${NC}"
    line ""
    line "  ${GY}Manage:${NC}  systemctl status ${SYSTEMD_SERVICE}"
    line "  ${GY}Logs:${NC}    journalctl -u ${SYSTEMD_SERVICE} -f"
    line ""
}

# ═══════════════════════════════════════
#  D O C K E R
# ═══════════════════════════════════════
setup_docker() {
    info "Docker mode: setting up docker-compose..."
    local data_dir_abs=$(cd "$DATA_DIR" && pwd)
    local jwt_secret; jwt_secret=$(openssl rand -base64 48 2>/dev/null)
    
    cat > "$INSTALL_DIR/docker-compose.yml" << EOF
# version removed (deprecated)
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
      - DATA_DIR=/app/data
$( [[ "$TLS_MODE" == "le" || "$TLS_MODE" == "le-ip" ]] && echo "      - SSL_KEYFILE=/app/certs/privkey.pem" && echo "      - SSL_CERTFILE=/app/certs/fullchain.pem" )
$( [[ "$TLS_MODE" == "self" ]] && echo "      - SSL_KEYFILE=/app/certs/privkey.pem" && echo "      - SSL_CERTFILE=/app/certs/fullchain.pem" )
$( [[ "$TLS_MODE" == "custom" ]] && echo "      - SSL_KEYFILE=/app/certs/privkey.pem" && echo "      - SSL_CERTFILE=/app/certs/fullchain.pem" )
    volumes:
      - ${data_dir_abs}:/app/data
$( [[ "$TLS_MODE" == "le" || "$TLS_MODE" == "le-ip" ]] && echo "      - /etc/letsencrypt/${TLS_DOMAIN}:/app/certs:ro")
$( [[ "$TLS_MODE" == "self" ]] && echo "      - /etc/ssl/self-signed:/app/certs:ro")
$( [[ "$TLS_MODE" == "custom" ]] && echo "      - /etc/letsencrypt/${TLS_DOMAIN}:/app/certs:ro")
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

# ═══════════════════════════════════════
#  U P D A T E
# ═══════════════════════════════════════
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

# ═══════════════════════════════════════
#  U N I N S T A L L
# ═══════════════════════════════════════
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
    rm -rf "$DATA_DIR"
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

    case "$ACTION" in
        uninstall)
            do_uninstall; exit 0 ;;
        update)
            do_update; exit 0 ;;
    esac

    if [[ -d "$INSTALL_DIR" ]]; then
        warn "OVManager is already installed"
        line ""
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
        field "Data dir"    "$DATA_DIR"
        field "Install mode" "$([ $DOCKER_FLAG -eq 1 ] && echo Docker || echo Native)"
        sep
    fi

    check_root
    check_deps
    do_install
}

main "$@"