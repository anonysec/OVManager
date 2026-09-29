# OVManager

[![Version](https://img.shields.io/badge/version-1.0.0-blue)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/anonysec/OVManager/actions/workflows/ci.yml/badge.svg)](https://github.com/anonysec/OVManager/actions/workflows/ci.yml)

Web panel for an OpenVPN service: users, traffic quotas, expiry dates, live
sessions, and the servers that carry the VPN. The panel holds the state. Each
VPN server runs [OVNode](https://github.com/anonysec/OVNode), which owns
OpenVPN, the certificates and the per-user configs. Nodes never call the panel,
so you can move or replace the panel without touching them.

## Install

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
```

Answer `1` to install natively (a systemd service on this host) or `2` for
Docker. The recommended install asks nothing: port `2095`, a random secret URL
path, admin user `admin`, self-signed TLS.

It ends with a one-time claim key and the panel URL:

```text
Open      https://203.0.113.10:2095/k3f9xq2m/claim
Claim key 9f1c...  (one-time)
Login     admin
```

Open that URL, paste the key, and choose the owner password. No password exists
until you do: the install mints a key, not a credential, and the password is
stored as a bcrypt hash in the panel database, never in `.env`. The key is spent
by the claim, and `sudo ovm owner-claim` prints a fresh one while the panel is
unclaimed.

For the wizard that asks about every setting instead:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) interactive
```

Unattended, for scripts and CI:

```bash
curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh \
  | sudo bash -s -- --yes

curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh \
  | sudo bash -s -- --docker --yes
```

The installer takes three flags: `-y/--yes`, `--docker`, `-h/--help`. Every
other setting is an `OVM_*` variable, so an unattended run and an interactive
one cannot disagree:

| Variable | Values |
| --- | --- |
| `OVM_PORT` | Panel port (default `2095`) |
| `OVM_PATH` | Secret URL prefix: `random` (default), `root`, or a name |
| `OVM_ADMIN_USER` | Owner login name (default `admin`) |
| `OVM_TLS` | `self` (default), `le`, `le-ip`, `custom` |
| `OVM_TLS_DOMAIN`, `OVM_TLS_KEY`, `OVM_TLS_CERT` | For `le` and `custom` |
| `OVM_PUBLIC_URL` | Address used in subscription links, when it cannot be inferred |
| `OVM_VERSION` | Pin an update to one release |
| `OVM_REPO` | `myorg/OVManager` to install and update from a fork |

`CI=true` implies `--yes`. The older flag spellings (`-p/--pass`, `--mode`,
`--tls*`, `-i`) still work and each prints what replaces it. Full list:
`bash install.sh --help`.

## What you get

| | |
| --- | --- |
| **Users** | Create with a traffic quota, expiry date and device limit. Tags group them (`vip`, `reseller-a`). Disable, extend, disconnect or delete from the row. |
| **Delivery** | A subscription link and a downloadable `.ovpn` per user, either one, per node. |
| **Nodes** | Add a node by address and API key, or paste its `ovnode://` bundle. Live reachability, session counts, OpenVPN/agent version, and per-node DNS, IPv6 and extra ports. |
| **Accounting** | Every five minutes the panel reads each node's lifetime byte totals and bills only the increase, so restarts and disconnects cannot double-count. Quota crossings are enforced on the spot. |
| **Limits** | The device limit is pushed to the node and enforced at connect time, so it holds even while the panel is down. |
| **Security** | Login sessions are opaque database rows. Failed logins are rate-limited per user and per IP. The panel is served under a secret URL prefix that returns an empty 404 anywhere else. |
| **Backups** | `ovm backup` writes a verified `.ovmbak` bundle. Schedule one inside the panel or with a systemd timer, and push a copy to your own SSH host. Restores are atomic. |
| **Audit and admins** | A filterable event log, and extra admin accounts the owner can enable or disable. |
| **Telegram bot** | Off by default. Status, user actions and alerts from the phone. The panel can also send a backup file to Telegram. Locales: `en`, `fa`, `ru`, `cn`. |
| **Updates** | Staged and verified, with automatic rollback when the new version fails to come up. |

## Day to day

`ovm` (alias `ovmanager`) is installed on the server and refreshed by every
update. Every command needs root, because each one reads the panel's `.env`.
The panel itself does not: any account can log in through the browser.

```bash
sudo ovm status          # service, health, version, panel URL (--all for paths)
sudo ovm doctor          # 13 health checks (--fix applies the safe ones)
sudo ovm logs            # last 100 lines; logs -f follows
sudo ovm backup          # verified data backup now (--keep N, default 14)
sudo ovm restore         # list backups, or restore one by name
sudo ovm auto-backup on  # daily backup timer (--time HH:MM)
sudo ovm https           # self-signed, Let's Encrypt, or your own certificate
sudo ovm tls-status      # the certificate in use and when it expires
sudo ovm update          # staged update that rolls back if the panel does not come up
sudo ovm rollback        # restore the newest pre-update code snapshot
sudo ovm recover-update  # clean up an update interrupted by a reboot
sudo ovm owner-claim     # new one-time claim key (before the panel is claimed)
sudo ovm reset-password  # set a new owner password
sudo ovm reset-urlpath   # clear the secret URL prefix
sudo ovm uninstall       # remove the app; --purge deletes the data too
```

`ovm` on its own prints that list, and `sudo ovm completion` installs bash
completion for it. `start`, `stop`, `restart`, `enable` and `disable` control
the service, `recovery` reprints the panel URL and login name, and
`version-script` prints which installer release you are running.

## Docs

| Document | What is in it |
| --- | --- |
| [quickstart](docs/quickstart.md) | The first run, step by step |
| [how it works](docs/how-it-works.md) | Process model, traffic accounting, security, updates, the design system |
| [nodes](docs/nodes.md) | OVNode on the same server or on its own, ports and firewall |
| [troubleshooting](docs/troubleshooting.md) | Lost URL, forgotten password, red nodes, no internet through the tunnel |
| [contributing](docs/CONTRIBUTING.md) | Ground rules, manual install, the checks, release freeze |
| [installer design](docs/adr/installer-design.md) | Why the installer and the CLI look the way they do |

## Acceptable use

You operate the VPN. Abuse complaints (spam, scanning, copyright) come to you,
not to this project. Enforce per-user quotas and expiry, watch the connection
events under Settings → Security, disable abusers promptly, and respect your
provider's terms of service and local law.

## License

MIT. Free for personal and commercial use: no license server, no paid feature
gate, no node or user limit. Keep the copyright and MIT license notice with
copies or substantial portions of the software.

See [Privacy](docs/legal/PRIVACY.md),
[Acceptable use](docs/legal/ACCEPTABLE_USE.md) and
[third-party licensing](docs/legal/THIRD_PARTY_LICENSES.md).
