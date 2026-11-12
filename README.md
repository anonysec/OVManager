# OVManager

Self-hosted OpenVPN admin panel: users, traffic quotas, expiry dates, device limits, and live sessions, across one server or many.

**2.0.0 is the first supported release.** The database (`app.db`), schema and
state formats start here; pre-2.0.0 installs are not upgradable. The panel
terminates TLS itself — there is no reverse-proxy mode. OpenVPN tuning is set
per node from the drawer, not in `.env`.

**Install (fresh Debian/Ubuntu, as root):**

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
```

**Documentation:** [https://anonysec.github.io/OVManager/](https://anonysec.github.io/OVManager/)

- Install & first login, nodes, users, traffic, TLS, backups, troubleshooting, CLI
- API contract, configuration, decisions, changelog, FAQ

**Pairs with:** [OVNode](https://github.com/anonysec/OVNode) — the agent that runs OpenVPN on each VPN server.

[![Version](https://img.shields.io/badge/version-2.0.5-blue)](https://anonysec.github.io/OVManager/wiki/changelog.html)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/anonysec/OVManager/actions/workflows/ci.yml/badge.svg)](https://github.com/anonysec/OVManager/actions/workflows/ci.yml)
