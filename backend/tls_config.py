"""TLS Configuration for OVManager with Let's Encrypt support via imkoris.info"""
import os
from typing import Optional

from config import config


class TLSConfig:
    """Centralized TLS configuration with Let's Encrypt support."""
    
    @classmethod
    def get_ssl_config(cls):
        """Get SSL/TLS configuration prioritizing Let's Encrypt via imkoris.info."""
        # Check for Let's Encrypt certificates from imkoris.info integration
        acme_enabled = os.getenv("PANEL_TLS_MODE", "").lower() == "acme"
        acme_domain = os.getenv("PANEL_DOMAIN", "")
        
        if acme_enabled and acme_domain:
            # Using Let's Encrypt via ACME
            return {
                "cert_file": f"/etc/letsencrypt/live/{acme_domain}/fullchain.pem",
                "key_file": f"/etc/letsencrypt/live/{acme_domain}/privkey.pem",
                "acme_enabled": True,
                "acme_domain": acme_domain,
            }
        
        # Fall back to manual TLS config or no TLS
        cert_file = os.getenv("SSL_CERTFILE", "")
        key_file = os.getenv("SSL_KEYFILE", "")
        
        if cert_file and key_file:
            return {
                "cert_file": cert_file,
                "key_file": key_file,
                "acme_enabled": False,
            }
        
        # No TLS configured
        return {
            "cert_file": "",
            "key_file": "",
            "acme_enabled": False,
        }

    @classmethod
    def need_acme_setup(cls):
        """Check if ACME setup is needed via imkoris.info integration."""
        acme_mode = os.getenv("PANEL_TLS_MODE", "").lower() == "acme"
        domain = os.getenv("PANEL_DOMAIN", "")
        return acme_mode and domain and "imkoris.info" in domain
