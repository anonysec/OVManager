# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""TLS configuration for OVManager.

Cert paths follow the convention set by the installer:
  - Let's Encrypt:  /etc/letsencrypt/<domain>/fullchain.pem + privkey.pem
  - Self-signed:    /etc/ssl/self-signed/cert.pem + key.pem

Priority: SSL_CERTFILE/SSL_KEYFILE env vars > auto-detect from PANEL_DOMAIN.
"""

import os


class TLSConfig:
    """Centralized TLS configuration."""

    @classmethod
    def get_ssl_config(cls) -> dict:
        """Return cert/key paths. Empty strings mean no TLS."""
        # 1. Explicit env vars (set by installer or Docker)
        cert_file = os.getenv("SSL_CERTFILE", "")
        key_file = os.getenv("SSL_KEYFILE", "")
        if cert_file and key_file:
            return {"cert_file": cert_file, "key_file": key_file}

        # 2. Auto-detect from PANEL_DOMAIN (Let's Encrypt)
        domain = os.getenv("PANEL_DOMAIN", "")
        if domain:
            le_cert = f"/etc/letsencrypt/{domain}/fullchain.pem"
            le_key = f"/etc/letsencrypt/{domain}/privkey.pem"
            if os.path.isfile(le_cert) and os.path.isfile(le_key):
                return {"cert_file": le_cert, "key_file": le_key}

        # 3. Auto-detect self-signed fallback
        ss_cert = "/etc/ssl/self-signed/cert.pem"
        ss_key = "/etc/ssl/self-signed/key.pem"
        if os.path.isfile(ss_cert) and os.path.isfile(ss_key):
            return {"cert_file": ss_cert, "key_file": ss_key}

        # 4. No TLS
        return {"cert_file": "", "key_file": ""}
