#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Part of scripts/lib (the simulated installer repo): sourced by manager.sh,
# and fetched and sourced by install.sh at startup (curl-pipe standalone).
# One definition per helper — tests/test_lib_sourcing.py enforces that.
# Pure helpers only.
# TLS: self-signed, acme.sh, Let's Encrypt, setup dispatch.

_is_docker_install() {  # MODE when the installer set it, else the compose file's presence
    if [[ -n "${MODE:-}" ]]; then
        [[ "$MODE" == "docker" ]]
    else
        [[ -n "${COMPOSE_FILE:-}" && -f "${COMPOSE_FILE:-}" ]]
    fi
}

secure_tls_files() {
    local key="$1" cert="$2"
    if [[ -f "$key" ]]; then
        # Who reads this key depends on the deployment, and getting it wrong is
        # not cosmetic: the key becomes unreadable by whoever serves TLS and
        # the panel dies on its next start. Docker reads it as the image's
        # appuser (uid 1000) through a read-only mount, so ownership is what
        # lets it in. The native panel is a service account that reads through
        # the group, and nothing on this path runs as root on its behalf —
        # chowning to 1000 unconditionally is what made `ovm https --self`
        # restart straight into a PermissionError from inside uvicorn.
        if _is_docker_install; then
            chown 1000:1000 "$key" 2>/dev/null || true
            chmod 600 "$key"
        else
            chgrp "${PANEL_USER:-ovmanager}" "$key" 2>/dev/null || true
            chmod 640 "$key"
        fi
    fi
    [[ -f "$cert" ]] && chmod 644 "$cert"
    return 0
}

_existing_tls_pair_usable() {  # <key> <cert> → 0 when an intact, unexpired pair is already there
    local key="$1" cert="$2" key_pub cert_pub
    [[ -s "$key" && -s "$cert" ]] || return 1
    openssl x509 -noout -checkend 0 -in "$cert" >/dev/null 2>&1 || return 1
    key_pub="$(openssl pkey -pubout -in "$key" 2>/dev/null | openssl sha256)" || return 1
    cert_pub="$(openssl x509 -pubkey -noout -in "$cert" 2>/dev/null | openssl sha256)" || return 1
    [[ -n "$key_pub" && "$key_pub" == "$cert_pub" ]]
}

generate_self_signed() {
    info "Self-signed certificate…"
    local key="/etc/ssl/self-signed/privkey.pem"
    local cert="/etc/ssl/self-signed/fullchain.pem"
    mkdir -p /etc/ssl/self-signed
    # /etc/ssl/self-signed is shared with OVNode on the same host: regenerating
    # replaces the node's identity and invalidates the certificate the panel
    # pinned for it, so an intact pair is kept and only its permissions are
    # re-asserted. `ovm https --self` is the explicit way to ask for a new one.
    if [[ "${TLS_REGENERATE:-0}" != "1" ]] && _existing_tls_pair_usable "$key" "$cert"; then
        TLS_KEY="$key"
        TLS_CERT="$cert"
        secure_tls_files "$key" "$cert"
        step "Certificate  $TLS_CERT  (existing — reused)"
        return 0
    fi
    local cn; cn="$(hostname -I 2>/dev/null | awk '{print $1}')"
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$key" \
        -out "$cert" \
        -subj "/C=US/ST=Local/L=Local/O=OVManager/CN=${cn}" >/dev/null 2>&1
    secure_tls_files "$key" "$cert"
    TLS_KEY="$key"
    TLS_CERT="$cert"
    step "Certificate  $TLS_CERT"
}

ACME_INSTALL_VERSION="3.1.1"

# Download a third-party installer to a file and run it, instead of piping
# curl straight into a root shell. Not a signature check — it stops a corrupt
# or truncated response and an obvious redirect stub, not a compromised vendor,
# which is why package-manager installs are tried first.
fetch_and_run_installer() {  # url expected-prefix tmpname
    local url="$1" prefix="$2" name="$3" script first rc
    script="$(mktemp "/tmp/${name}.XXXXXX.sh")"
    if ! curl -fsSL --max-time 60 -o "$script" -- "$url"; then
        rm -f "$script"
        return 1
    fi
    first="$(head -c 200 "$script" 2>/dev/null || true)"
    case "$first" in
        *"$prefix"*) : ;;
        *) rm -f "$script"; return 1 ;;
    esac
    sh "$script" >/dev/null 2>&1
    rc=$?
    rm -f "$script"
    return $rc
}

ensure_acme() {
    [[ -x "$HOME/.acme.sh/acme.sh" ]] && return 0
    info "Installing acme.sh…"
    # get.acme.sh is a moving target; the tagged release is not, and this
    # install runs as root.
    fetch_and_run_installer \
        "https://raw.githubusercontent.com/acmesh-official/acme.sh/${ACME_INSTALL_VERSION}/acme.sh" \
        "#!/usr/bin/env sh" "acme-install" \
        || fetch_and_run_installer \
        "https://raw.githubusercontent.com/acmesh-official/acme.sh/${ACME_INSTALL_VERSION}/acme.sh" \
        "#!/bin/sh" "acme-install" \
        || die "Failed to install acme.sh — install certbot instead: apt install certbot"
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
            step "Existing certificate valid ${days_left}d"
            return 0
        fi
        warn "Certificate expires in ${days_left}d — renewing"
    fi
    local extra_args=()
    if [[ "$is_ip" == "1" ]]; then
        info "Short-lived certificate for IP $domain…"
        extra_args=(--certificate-profile shortlived --days 6)
    else
        info "Let's Encrypt for $domain…"
    fi
    "$HOME/.acme.sh/acme.sh" --issue -d "$domain" --standalone "${extra_args[@]}" \
        --accountemail "$email" >/dev/null 2>&1 \
        || die "Failed to issue Let's Encrypt certificate for $domain"
    "$HOME/.acme.sh/acme.sh" --install-cert -d "$domain" \
        --key-file "$outdir/privkey.pem" \
        --fullchain-file "$outdir/fullchain.pem" \
        --reloadcmd "if [ -f $COMPOSE_FILE ]; then chown 1000:1000 $outdir/privkey.pem 2>/dev/null || true; chmod 600 $outdir/privkey.pem; else chgrp ${PANEL_USER:-ovmanager} $outdir/privkey.pem 2>/dev/null || true; chmod 640 $outdir/privkey.pem; fi; chmod 644 $outdir/fullchain.pem; systemctl restart $SYSTEMD_SERVICE >/dev/null 2>&1 || docker restart ovmanager >/dev/null 2>&1 || true" \
        >/dev/null 2>&1 || die "Failed to install certificate to $outdir"
    # Renewals re-apply permissions through the reloadcmd above, which has to
    # branch the same way this function does — it runs later, on its own, long
    # after these variables are gone, so it cannot call back into here.
    secure_tls_files "$outdir/privkey.pem" "$outdir/fullchain.pem"
    step "Certificate  $outdir"
}

setup_tls() {
    case "$TLS_MODE" in
        le)
            port_in_use 80 && die "Port 80 is busy — Let's Encrypt standalone needs it (or --tls 1 for now)"
            issue_lets_encrypt "$TLS_DOMAIN" "0"
            TLS_KEY="/etc/letsencrypt/$TLS_DOMAIN/privkey.pem"
            TLS_CERT="/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem"
            ;;
        le-ip)
            port_in_use 80 && die "Port 80 is busy — Let's Encrypt standalone needs it (or --tls 1 for now)"
            TLS_DOMAIN="${TLS_DOMAIN:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
            issue_lets_encrypt "$TLS_DOMAIN" "1"
            TLS_KEY="/etc/letsencrypt/$TLS_DOMAIN/privkey.pem"
            TLS_CERT="/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem"
            ;;
        self) generate_self_signed ;;
        custom)
            [[ -f "$TLS_KEY" && -f "$TLS_CERT" ]] || die "Custom key/cert not found: $TLS_KEY $TLS_CERT"
            local out="/etc/letsencrypt/${TLS_DOMAIN:-panel}"
            mkdir -p "$out"
            cp "$TLS_KEY" "$out/privkey.pem"
            cp "$TLS_CERT" "$out/fullchain.pem"
            secure_tls_files "$out/privkey.pem" "$out/fullchain.pem"
            TLS_KEY="$out/privkey.pem"; TLS_CERT="$out/fullchain.pem"
            ;;
        none) ;;
        *) die "Invalid TLS mode: '$TLS_MODE'" ;;
    esac
}
