# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Where the certificate lives. One answer, for every part of the system.

There used to be two answers and a hidden winner. ``SSL_KEYFILE`` and
``SSL_CERTFILE`` in ``.env`` named one location; ``DATA_DIR/tls/`` held another;
and ``main.py`` preferred the second without saying so. An operator who
carefully installed a certificate at the path in ``.env`` got a panel that
quietly kept serving the old one.

The rule now:

* ``.env`` declares. It is written once by the installer and never edited
  again, so a declaration there is a fact, not a suggestion.
* When it is silent, there is one default: ``/etc/ovmanager/tls``. Chosen over
  ``DATA_DIR/tls`` because a backup, a data-directory wipe or a container mount
  must not be able to take the server's private key with it.
* Everyone who needs the path — the installer, ``ovm tls``, the panel's
  certificate router, uvicorn — asks here. Nobody derives it from a mode name.

``/etc/ssl/self-signed`` is still honoured where ``.env`` declares it, so
existing installs are untouched. What is gone is the ability for the software to
quietly serve something other than what the operator can see.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DIR = "/etc/ovmanager/tls"
KEY_NAME = "privkey.pem"
CERT_NAME = "fullchain.pem"


def _declared(name: str) -> str:
    """The declared value, from whichever layer the panel is actually using.

    ``backend.config.config`` first, because that is the pydantic object every
    other caller reads and the one tests override. The environment is the
    fallback for the paths where settings is not built yet — importing
    ``config`` at module scope would make this a circular import through
    ``backend.data_paths``.

    Reading the environment first instead would be a second source of truth for
    one setting, which is the exact class of bug this module exists to remove.
    """
    try:
        from backend.config import config

        value = (getattr(config, name, None) or "").strip()
        if value:
            return value
    except Exception:
        pass
    return (os.environ.get(name) or "").strip()


def key_path() -> Path:
    """The private key the panel will serve with."""
    return Path(_declared("SSL_KEYFILE") or f"{DEFAULT_DIR}/{KEY_NAME}")


def cert_path() -> Path:
    """The certificate the panel will serve with."""
    return Path(_declared("SSL_CERTFILE") or f"{DEFAULT_DIR}/{CERT_NAME}")


def declared() -> bool:
    """True when ``.env`` names the pair itself.

    The difference matters for one thing: an install that declares gets its
    existing paths forever, while one that does not gets the default — and only
    the first kind is worth migrating onto.
    """
    return bool(_declared("SSL_KEYFILE") and _declared("SSL_CERTFILE"))
