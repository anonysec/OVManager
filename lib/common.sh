SSL_KEY_SRC=""
SSL_IP=""
INSTALL_IP_SSL=0
INSTALL_SELF_SIGNED=0
SELF_SIGNED_TARGET=""

# ── Capability detection (OVNode-compatible) ────────────────────────
if [[ -t 2 && -z "${NO_COLOR:-}" && "${TERM:-dumb}" != "dumb" ]]; then
    RENDER_COLOR=1
else
    RENDER_COLOR=0
fi
if [[ "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" == *[Uu][Tt][Ff]* ]]; then
    RENDER_SPINNER_UNICODE=1
else
    RENDER_SPINNER_UNICODE=0
fi
NC=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'
WH=$'\033[97m'; GR=$'\033[32m'; RD=$'\033[31m'
YL=$'\033[33m'; CY=$'\033[36m'; GY=$'\033[90m'
OR=$'\033[38;5;208m'
[[ "$RENDER_COLOR" -eq 1 ]] || { NC=''; B=''; D=''; WH=''; GR=''; RD=''; YL=''; CY=''; GY=''; OR=''; }
if [[ "$RENDER_SPINNER_UNICODE" -eq 1 ]]; then
    RENDER_OK='✓'; RENDER_BAD='✗'; RENDER_RULE='──────────────────────────────────────────────'
else
    RENDER_OK='ok'; RENDER_BAD='XX'; RENDER_RULE='----------------------------------------------'
fi
[[ -t 2 ]] || { NC=''; B=''; D=''; WH=''; GR=''; RD=''; YL=''; CY=''; GY=''; OR=''; }

_render_paint() { if [[ "$RENDER_COLOR" -eq 1 ]]; then printf '%b%s%b' "$1" "$2" "${NC:-}"; else printf '%s' "$2"; fi; }
_render_out() { printf '  %b\n' "$*" >&2; }

# Legacy aliases (kept for existing call sites)
_GREEN="$GR"; _YELLOW="$YL"; _BLUE="$CY"; _RED="$RD"; _CYAN="$CY"
_BOLD="$B"; _DIM="$D"; _RESET="$NC"
colorized_echo() {
    local color="$1"; shift
    case "$color" in
        green)  printf '%s%s%s\n' "$GR" "$*" "$NC" >&2 ;;
        yellow) printf '%s%s%s\n' "$YL" "$*" "$NC" >&2 ;;
        red)    printf '%s%s%s\n' "$RD" "$*" "$NC" >&2 ;;
        blue)   printf '%s%s%s\n' "$CY" "$*" "$NC" >&2 ;;
        cyan)   printf '%s%s%s\n' "$CY" "$*" "$NC" >&2 ;;
        *)      printf '%s\n' "$*" >&2 ;;
    esac
}
_ok()    { render_ok "$*"; }
_warn()  { render_warn "$*"; }
_err()   { render_fail "$*" "error"; }
_note()  { render_ask_note "$*"; }

section() { render_stage "$*"; }
step() { printf '%s[%s/%s]%s %s\n' "$D" "$1" "$2" "$NC" "$3" >&2; }

die()    { printf '\n  %sError:%s %s\n\n' "$RD" "$NC" "$*" >&2; exit 1; }

has_systemd() { command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; }
check_root()  { [[ "$EUID" -eq 0 ]] || die "Must run as root (sudo)."; }
install_packages() {
    local pkgs=("$@")
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq >/dev/null 2>&1 || true
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${pkgs[@]}" >/dev/null 2>&1 || return 1
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y -q "${pkgs[@]}" >/dev/null 2>&1 || return 1
    elif command -v yum >/dev/null 2>&1; then
        yum install -y -q "${pkgs[@]}" >/dev/null 2>&1 || return 1
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache "${pkgs[@]}" >/dev/null 2>&1 || return 1
    else
        return 1
    fi
    return 0
}

check_deps() {
    local missing_pkgs=()
    command -v curl >/dev/null 2>&1 || missing_pkgs+=("curl")
    command -v openssl >/dev/null 2>&1 || missing_pkgs+=("openssl")
    if [[ ${#missing_pkgs[@]} -gt 0 ]]; then
        _note "installing missing dependencies: ${missing_pkgs[*]}"
        install_packages "${missing_pkgs[@]}" || die "Could not install: ${missing_pkgs[*]}"
    fi
    for cmd in curl install sha256sum openssl; do
        command -v "$cmd" >/dev/null 2>&1 || die "Missing required tool: $cmd"
    done
}

is_domain() { [[ "$1" =~ ^([A-Za-z0-9](-*[A-Za-z0-9])*\.)+(xn--[a-z0-9]{2,}|[A-Za-z]{2,})$ ]]; }
is_ipv4() {
    local ip="$1" IFS='.' octets=()
    [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
    read -r -a octets <<<"$ip"
    [[ ${#octets[@]} -eq 4 ]] || return 1
    for octet in "${octets[@]}"; do (( octet >= 0 && octet <= 255 )) || return 1; done
    return 0
}
is_ipv6() { [[ "$1" =~ : ]]; }
is_port_in_use() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk -v p=":${port}$" '$4 ~ p {found=1; exit} END {exit found ? 0 : 1}'
        return
    fi
    if command -v netstat >/dev/null 2>&1; then
        netstat -lnt 2>/dev/null | awk -v p=":${port} " '$4 ~ p {found=1; exit} END {exit found ? 0 : 1}'
        return
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1 && return 0
    fi
    return 1
}
get_public_ipv4() {
    local urls=("https://api4.ipify.org" "https://ipv4.icanhazip.com" "https://v4.ident.me")
    local server_ip url
    for url in "${urls[@]}"; do
        server_ip=$(curl -4 -fsS --max-time 5 "$url" 2>/dev/null | tr -d '[:space:]' || true)
        if is_ipv4 "$server_ip"; then printf '%s' "$server_ip"; return 0; fi
    done
    return 1
}

detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64) printf 'amd64' ;;
        aarch64|arm64) printf 'arm64' ;;
        *) die "Unsupported architecture: $(uname -m)" ;;
    esac
}
release_asset() { printf '%s-linux-%s' "$APP_SLUG" "$(detect_arch)"; }
release_url() { printf 'https://github.com/%s/releases/download/v%s/%s' "$REPO" "$VERSION" "$(release_asset)"; }
release_checksum_url() { printf '%s.sha256' "$(release_url)"; }

fetch_release() {
    local dest="$1" work asset retries=0
    asset="$(release_asset)"
    work="$(mktemp -d)"
    _note "fetching v$VERSION ($asset)"
    while true; do
        if curl -fsSL --max-time 300 --retry 3 --retry-delay 2 --retry-max-time 600 -o "$work/$asset" "$(release_url)" 2>/dev/null; then
            break
        fi
        retries=$((retries + 1))
        if [[ $retries -ge 3 ]]; then rm -rf "$work"; die "No release file for v$VERSION"; fi
        sleep $((2 ** retries))
    done
    if ! curl -fsSL --max-time 120 --retry 2 -o "$work/$asset.sha256" "$(release_checksum_url)" 2>/dev/null; then
        rm -rf "$work"; die "Release checksum file is missing for v$VERSION"
    fi
    if ! ( cd "$work" && sha256sum -c "$asset.sha256" >/dev/null 2>&1 ); then
        rm -rf "$work"; die "Release checksum mismatch for v$VERSION"
    fi
    mkdir -p "$dest"
    install -m 0755 "$work/$asset" "$dest/$APP_SLUG"
    chown root:root "$dest/$APP_SLUG"
    rm -rf "$work"
    _ok "installed v$VERSION to $dest"
}

validate_port() { local p="$1"; [[ "$p" =~ ^[0-9]+$ ]] && [[ "$p" -ge 1 && "$p" -le 65535 ]]; }
validate_urlpath() {
    local p="$1"
    [[ "$p" != "api" && "$p" != "assets" && "$p" != "health" && "$p" != "static" && "$p" != "doc" && "$p" != "openapi.json" ]] || return 1
    [[ "$p" =~ ^[A-Za-z0-9_-]+$ ]]
}

# ── Interactive menu ────────────────────────────────────────────────────
# The install wizard is a sequence of small numbered menus over a shared
# frame: a blue rule, aligned numbered rows, and one prompt line at the end.
# Everything prints to stderr so `curl | bash` stays clean.

# ── OVNode render helpers (verbatim port) ────────────────────────────
RENDER_LABEL_W=14
_render_paint() { if [[ "$RENDER_COLOR" -eq 1 ]]; then printf '%b%s%b' "$1" "$2" "${NC:-}"; else printf '%s' "$2"; fi; }
_render_out() { printf '  %b\n' "$*" >&2; }

render_banner() {  # render_banner <name> <version>
    local name="$1" version="$2"
    _render_out "$(_render_paint "$B" "$name")  $version  $(_render_paint "$GY" "· anonysec")"
    render_rule
}

render_rule() { _render_out "$(_render_paint "$GY" "$RENDER_RULE")"; }

render_screen() {
    [[ -t 2 ]] || return 0
    clear 2>/dev/null || printf '\033[H\033[2J\033[3J' >&2 || true
    return 0
}

render_menu() {
    shift    # title is the caller's; the banner already said what this is
    local -a tags=() labels=()
    while [[ $# -ge 2 ]]; do tags+=("$1"); labels+=("$2"); shift 2; done
    local count=${#tags[@]}
    [[ "$count" -gt 0 ]] || return 1
    local i=0
    while (( i < count )); do
        printf '  %b%d%b  %s\n' "$B" "$(( i + 1 ))" "$NC" "${labels[$i]}" >&2
        i=$(( i + 1 ))
    done
    local n
    n="$(ask "choice" "1")"
    [[ "$n" =~ ^[0-9]+$ ]] || n=1
    printf '%s' "${tags[$(( ((10#$n - 1) + count) % count ))]}"
    return 0
}

RENDER_STEP_LABEL=""
render_begin() { RENDER_STEP_LABEL="$1"; printf '  %b..%b    %s\n' "$GY" "$NC" "$1" >&2; return 0; }
render_stage() { printf '\n  ============================== %s ==============================\n' "$1" >&2; return 0; }
render_done() { RENDER_STEP_LABEL=""; printf '  %b%s%b  %s\n' "$GR" "$RENDER_OK" "$NC" "${1:-}" >&2; return 0; }
render_end() { RENDER_STEP_LABEL=""; return 0; }
render_note() { printf '  %b..%b    %s\n' "$GY" "$NC" "$1" >&2; return 0; }
render_line() { _render_out "$*"; }
render_blank() { printf '\n' >&2; }
render_ok() { printf '  %b%s%b  %s\n' "$GR" "$RENDER_OK" "$NC" "$1" >&2; }
render_warn() { printf '  %b%s%b\n' "$YL" "$1" "$NC" >&2; }
render_kv() { printf '   %b%-*s%b %s\n' "$GY" "$RENDER_LABEL_W" "$1" "$NC" "$2" >&2; }
render_kv_w() { printf '   %b%-*s%b %s\n' "$GY" "$1" "$2" "$NC" "$3" >&2; }
render_key() { printf '   %b%-*s%b %b%s%b\n' "$GY" "$RENDER_LABEL_W" "$1" "$NC" "$B" "$2" "$NC" >&2; }
render_url() { render_kv "$1" "$(_render_paint "$B" "$2")"; }
render_fail() { RENDER_STEP_LABEL=""; printf '  %b%s%b %b%s%b  %s\n' "$RD" "$RENDER_BAD" "$NC" "$B" "$1" "$NC" "$2" >&2; return 0; }
render_next() { printf '  %bnext%b  %s · uninstall: %s\n' "$GY" "$NC" "$1" "$2" >&2; }
render_ask() { printf '  %b%s%b %b[%s]%b: ' "$GY" "$1" "$NC" "$B" "$2" "$NC" >&2; }
render_ask_note() { _render_out "$(_render_paint "$GY" "$1")"; }

# is_tty — OVNode-compatible: terminal on both ends.
is_tty() { [[ -t 0 && -t 2 ]]; }
ask() {
    local label="$1" default="$2" hidden="${3:-}" val=""
    if is_tty && [[ "${YES:-0}" -eq 0 ]]; then
        render_ask "$label" "$default"
        if [[ "$hidden" == "h" ]]; then
            local buf="" ch
            while IFS= read -rsn1 ch; do
                case "$ch" in
                    ""|$'\n'|$'\r') break ;;
                    $'\x7f'|$'\b') if [[ -n "$buf" ]]; then buf="${buf%?}"; printf '\b \b' >&2; fi ;;
                    *) buf+="$ch"; printf '*' >&2 ;;
                esac
            done
            printf '\n' >&2
            val="$buf"
        else
            read -r val
        fi
    fi
    echo "${val:-$default}"
}

# Legacy aliases kept for existing call sites.
ui_rule() { render_rule; }
ui_banner() { render_banner "$1" "$2"; }
ui_menu() { render_menu "" "$@"; }
_ok() { render_ok "$*"; }
_warn() { render_warn "$*"; }
_err() { render_fail "$*" "error"; }
_note() { render_ask_note "$*"; }
section() { render_stage "$*"; }
step() { printf '%s[%s/%s]%s %s\n' "$D" "$1" "$2" "$NC" "$3" >&2; }

