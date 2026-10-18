# OVManager

Web panel for a self-hosted VPN service: users, traffic quotas, expiry dates, device limits and live sessions, across one server or many.

<div align="center">
  <img src=".github/assets/banner.svg" alt="OVManager — self-hosted OpenVPN control panel" width="820">
  <br><br>

  [![Version](https://img.shields.io/badge/version-2.1.0-blue)](CHANGELOG.md)
  [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
  [![CI](https://github.com/anonysec/OVManager/actions/workflows/ci.yml/badge.svg)](https://github.com/anonysec/OVManager/actions/workflows/ci.yml)
  [![Go](https://img.shields.io/badge/go-1.27+-00ADD8?logo=go&logoColor=white)](go.mod)
  [![React](https://img.shields.io/badge/react-19-087ea4?logo=react&logoColor=white)](web/package.json)
  [![Runtime](https://img.shields.io/badge/runtime-systemd%20%7C%20docker-555555)](#-install)
</div>

## 📖 Table of contents

- [What is this?](#-what-is-this)
- [Why this one?](#-why-this-one)
- [Features](#-features)
- [Install](#-install)
- [After it finishes](#-after-it-finishes)
- [Performance notes](#-performance-notes)
- [Day-to-day commands](#-day-to-day-commands)
- [Docs](#-docs)
- [License](#-license)

## 🧭 What is this?

> OVManager is the control panel for a VPN you run yourself. It keeps the account list — who may connect, how much traffic they may use, and when their access ends — and hands each person a config file or a link they can re-fetch.
>
> The VPN traffic itself runs on separate servers. Each one carries a small agent that the panel installs, configures and reads traffic numbers from.
>
> The panel is the only place you have to log in.

## 💡 Why this one?

- **A first login with nothing to leak.** The installer never creates an owner password and never writes one to disk. It prints a one-time claim key; the owner account does not exist until a browser posts that key and chooses a password. A copy of the server's config file is worth nothing to an attacker.
- **Nothing is compiled on your server.** The installer downloads a bare release binary for this platform plus its mandatory SHA-256 sidecar and refuses to continue if the checksum does not match. The dashboard ships inside the binary; no compiler, no `git`, no `npm`, no runtime packages on the box.
- **The VPN servers are independent of the panel.** Nodes never call the panel and do not store its address, so the panel can be moved, rebuilt or replaced without touching a single VPN server. Re-attach them with the same address, name and key.
- **Limits that hold while the panel is down.** The device limit is pushed to each node and enforced there at connect time. The panel is not asked permission, and its absence changes nothing.
- **Accounting that cannot double-bill.** Each node reports a lifetime byte total per user; the panel remembers the last number it saw and bills only the increase. A dropped session, a restart or a rebuilt node cannot over-count.
- **Updates that undo themselves.** `sudo ovm update` downloads a verified release, stages it, health-checks the new version, and automatically restores the previous code if the panel does not come up.
- **A real API underneath.** The dashboard is a client of the panel's own JSON API and speaks the same login session.

## ✨ Features

### 📋 Panel and dashboard
- A React dashboard over a SQLite database — no external database, cache or message queue to run.
- Live view of sessions across every node, backed by one background collector instead of a request-time fan-out, so one dead node cannot stall the user list.
- Traffic history charted over the last 14 days.
- A startup checklist at `/setup` that keeps the first-run steps in front of you until they are done.
- Health centre that collects reachability, certificate and configuration problems in one page.
- Interface locales: English, Persian (RTL), Russian and Chinese.

### 👤 Users and subscriptions
- One page to create, edit, extend, disable, disconnect or delete an account, singly or in bulk.
- Per-user traffic quota in GB (empty means unlimited), expiry date, and device limit.
- Free-text tags up to 64 characters for grouping, search and filtering.
- Handoff straight after creation: download a `.ovpn` profile for a chosen node, or copy a subscription link. Both stay available from the user's row.
- Subscription links served outside the secret panel path, so they can actually be shared — with a QR code for phone clients.
- Additional admin accounts alongside the owner, each of which can be enabled or disabled, with their own sessions listed and revocable.

### 📊 Traffic accounting
- Usage collected every five minutes from every node, counted as the increase over the last reading — short sessions, disconnects and restarts cannot double-count, and a total that shrinks bills zero.
- Quota crossings enforced immediately after the tick that detects them; expiry-only cases caught by a separate ten-minute sweep.
- Conditional database writes, so an admin action landing mid-tick becomes a no-op rather than being overwritten by stale data.
- Warnings from 80% of quota, caught at the tick that detects them.
- Device limits enforced on the node, from 1 (a new connection takes over) through N (the N+1th is rejected) to 0 (unlimited).

### 🌐 Nodes
- Add a node with an address, port and API key, or paste its `the node installer output` bundle and let the form fill itself in.
- Test connection before saving; the node row then shows reachability, agent and OpenVPN version, and session counts.
- Per-node settings pushed from the panel: DNS servers, IPv6 pool and prefix, extra OpenVPN ports.
- Deleting a panel user also deletes them on every reachable node, so no ghost sessions survive the panel row.
- `2083` is the only port the panel needs; the node agent is installed by its own one-liner.

### 🔐 Security and TLS
- Login sessions are opaque tokens in the database, stored as a SHA-256 hash, sliding on activity and revocable per account.
- Rate limits on failed logins, per username and per address, with a `Retry-After` on the claim endpoint.
- The panel is served under a random secret URL prefix; anything outside it gets an empty 404, so scanners see nothing.
- Strict security headers on every response (CSP, `X-Frame-Options: DENY`, nosniff), with HSTS added when the connection is TLS.
- Terminate HTTPS at a fronting proxy (nginx/Caddy) or set `SSL_CERTFILE`/`SSL_KEYFILE` in `.env`; `ovm tls` shows the installed certificate.
- Built-in Let's Encrypt (`ovm tls acme <domain>` or `install.sh --acme DOMAIN`) issues over HTTP-01: **port 80 must be free** on this server for up to ~60 seconds while the certificate is issued, then renewals happen automatically (T-30 days). Anything else bound to port 80 makes issuance fail; the panel keeps serving plain HTTP meanwhile.
- Node connections verify TLS strictly first and warn once per node when a self-signed certificate forces a fallback.
- Secrets live in the database, not in `.env`; the data directory is `0700` and the database and every backup bundle are `0600`.
- A filterable audit log of who changed what, exportable as CSV.

### 🤖 Automation and API
- Backup scheduler: the installer writes a daily systemd timer (`ovm-backup.timer`) that runs a verified backup and prunes to 7 copies, whether or not the panel process is up.
- Public subscription endpoint that answers with a page, a usage summary or the `.ovpn` itself.
- Staged updates and every manual-verifying step are fully scripted.

### 🔧 Operations
- `ovm doctor` runs the health checks over the service, autostart, file modes, data directory, disk space, worker, HTTP health and backup age and certificate.
- Staged updates with automatic failover; an update interrupted by a reboot is recovered on the next `ovm update` run.
- Verified `.db` backups, listed and restored by name (`ovm backup --keep N`, `ovm restore`).
- A bare `ovm` run prints the available screens and exits; every command has `--help`.

## 🚀 Install

**Before you start:**

- A Linux server — Debian or Ubuntu recommended.
- Root, or an account with `sudo`.
- A host with systemd.
- Port `2095` free.

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
```

The installer fetches the bare release binary for this platform (plus its SHA-256 sidecar, verified before install), puts it in `/opt/ovmanager`, writes a systemd service and a daily backup timer, starts the panel and health-checks the result. There is nothing to prompt for; `-y` is accepted for compatibility and the script never asks questions mid-run. `bash install.sh --help` prints the full surface.

**From source** (development): point the installer at a working tree — it builds the SPA and the binary in place:

```bash
bash install.sh --build [SRC] [--dest DIR]
```

**Docker instead of systemd:** the pre-built image publishes on every release:

```bash
docker run -d --name ovmanager -p 2095:2095 -v ovmanager-data:/data \
  ghcr.io/anonysec/ovmanager
```

## 🏁 After it finishes

The install ends with a **Ready** card holding the panel URL and a one-time claim key:

```text
panel          https://203.0.113.10:2095/a1b2c3d4/setup
setup key      9f1c8b2e…  (one-time)
user           admin — change it any time in Settings
```

**First login.** Open the URL, paste the key, and choose the owner password — at least 8 characters, and not a placeholder like `change-me`. No password exists until you do this. On a panel nobody has claimed yet, that address shows the claim form; once claimed, the same address is the setup checklist. The key is spent the moment it works, and the password is stored as a bcrypt hash in the panel database, never in `.env`. Lost the key before claiming? `sudo ovm owner-claim` prints a fresh one. Claimed already and lost the password? `sudo ovm reset-password`.

**Where things live:**

| Path | What |
| --- | --- |
| `/opt/ovmanager` | The installed tree: the binary (with the dashboard inside), `.env` |
| `/opt/ovmanager/.env` | Configuration — port, data dir, owner login name |
| `/var/lib/ovmanager` | The database, backups and node material (mode `0700`) |
| `/usr/local/bin/ovm` | Symlink to the binary — the operator CLI |
| `.github/site` | Not on disk: the docs are the Pages site below |

**Then attach a server.** The panel manages accounts; it does not carry VPN traffic. Install OVNode on the machine your users will connect to and register it under **Nodes → Add Node** — the panel's Ready card prints a ready-to-paste command with the API key already filled in. Until a node is green, the panel has nothing to hand out.

**Managing it afterwards** is `ovm`, a symlink to the same binary that serves the panel. Run it bare for a command list, or `--help` per command. There is no `uninstall` command: stop the service and remove `/opt/ovmanager` and `/var/lib/ovmanager` (data is kept unless you remove it).

| What | How |
| --- | --- |
| Status, health, version, URL | `sudo ovm status [--all]` |
| Health checks | `sudo ovm doctor` |
| Service control | `sudo ovm service start \| stop \| restart \| enable \| disable` |
| Server logs | `sudo ovm logs [N\|-f]` |
| Backup now (verified, pruned) | `sudo ovm backup [--keep N]` — default 14 |
| List backups, or restore | `sudo ovm restore [NAME]` |
| The daily timer | written by the installer; runs `ovm backup --keep 7` daily |
| Panel URL prefix | `sudo ovm urlpath` |
| Installed certificate | `sudo ovm tls` |
| Staged update with failover | `sudo ovm update` |
| Reset the owner password | `sudo ovm reset-password` |
| Shell completion | `sudo ovm completion bash\|zsh\|fish` |

## ⚡ Performance notes

The panel is designed to be light on a small VPS and gentle on the nodes.

- **One collector, not one request per node.** A background collector polls every node and caches the result; request handlers read that snapshot, so a node that has stopped answering cannot stall a page.
- **Polling backs off when nobody is watching.** The live collector polls every 10 seconds while a browser has the live stream open and falls back to `OVMANAGER_LIVE_IDLE_POLL_SECONDS` (default `300`) when it does not. The public subscription page is still served from that snapshot, so it does not go stale.
- **Both of those are tunable** in `.env` as `OVMANAGER_LIVE_POLL_SECONDS` and `OVMANAGER_LIVE_IDLE_POLL_SECONDS`.
- **No Redis, on purpose.** A broker pays off when several application processes must share state. Here a single web process owns the live cache and the periodic jobs coordinate through SQLite, which is already the source of truth, so a Redis hop would add latency, memory and another service to operate without buying anything. It becomes worthwhile when the panel moves to multiple web workers — and that means replacing SQLite with a networked database first.
- **A bounded working set.** A scheduled job prunes the audit log and the daily traffic history on an age limit, so a long-running panel does not grow without limit.

## 🧰 Day-to-day commands

Every `ovm` command needs root, because each one reads the panel's `.env` to find the panel URL path and the install layout. The panel itself does not: any account can log in through the browser.

| Command | What it does |
| --- | --- |
| `sudo ovm status` | Service, health, version and panel URL. `--all` adds mode, port, data and install paths. |
| `sudo ovm doctor` | Run the health checks (service, autostart, modes, data dir, disk, worker, HTTP health, backup age, certificate). |
| `sudo ovm logs [N\|-f]` | Last N log lines (default 100), or follow live. |
| `sudo ovm service start \| stop \| restart` | Service control. `enable` / `disable` set automatic start. |
| `sudo ovm backup [--keep N]` | Write a verified backup now. `--keep` is 1–500, default 14. The installer's daily timer pins `--keep 7`. |
| `sudo ovm restore [NAME]` | List backups, or restore one by name. |
| `sudo ovm urlpath` | Print the secret URL prefix the panel is served under. |
| `sudo ovm tls` | The installed certificate and when it expires. Read-only. |
| `sudo ovm update` | Staged update with automatic failover; recovers an interrupted update first. |
| `sudo ovm reset-password` | Set a new owner password, then restart the panel. |
| `sudo ovm completion` | Install shell completion (`bash\|zsh\|fish\|powershell`). |

`ovm update` covers rollback too: the pre-update tree is kept, `ovm restore` restores backups, and an update interrupted mid-flight is recovered automatically at the next `ovm update` call.

## 📚 Docs

Full documentation is published at **<https://anonysec.github.io/OVManager/>**.

| Guide | What is in it |
| --- | --- |
| [Install & first login](https://anonysec.github.io/OVManager/wiki/install.html) | Requirements, the one-line installer, native vs Docker, the claim-key flow, update and uninstall, from-source install. |
| [How it works](https://anonysec.github.io/OVManager/wiki/how-it-works.html) | Process model, where the data lives, the security model, updates and the container image. |
| [Adding nodes](https://anonysec.github.io/OVManager/wiki/nodes.html) | Install the OVNode agent, register it in the panel, and get the firewall right. |
| [Users & subscriptions](https://anonysec.github.io/OVManager/wiki/users.html) | Create a user, choose quota and expiry, hand out a `.ovpn` or a subscription link. |
| [Traffic limits](https://anonysec.github.io/OVManager/wiki/traffic.html) | How usage is measured every five minutes, why it never double-counts, and what enforcement does. |
| [TLS certificates](https://anonysec.github.io/OVManager/wiki/tls.html) | Self-signed vs Let's Encrypt, renewing, and the node-side certificate story. |
| [Backups & restore](https://anonysec.github.io/OVManager/wiki/backup.html) | Backup bundles, the daily timer, offsite copies, and restoring without taking the panel down. |
| [Troubleshooting](https://anonysec.github.io/OVManager/wiki/troubleshooting.html) | The symptoms people actually hit, in the order worth checking. |
| [CLI reference](https://anonysec.github.io/OVManager/wiki/cli.html) | Every `ovm` and `ovn` command, the installer's flags, and the `OVM_*` settings. |

Elsewhere in this repository:

- [CONTRIBUTING.md](.github/CONTRIBUTING.md) — ground rules, manual install, the checks, release freeze.
- [SECURITY.md](SECURITY.md) — how to report a vulnerability.
- [CHANGELOG.md](CHANGELOG.md) — what changed in each release.

## 📄 License

MIT. Free for personal and commercial use: no license server, no paid feature gate, no node or user limit. Keep the copyright and MIT license notice with copies or substantial portions of the software.

**You operate the VPN.** Abuse complaints (spam, scanning, copyright) come to you, not to this project. Enforce per-user quotas and expiry, watch the connection events in the audit log, disable abusers promptly, and respect your provider's terms of service and local law.

See [Privacy](.github/docs/legal/PRIVACY.md), [Acceptable use](.github/docs/legal/ACCEPTABLE_USE.md), [Trademarks](.github/docs/legal/TRADEMARKS.md) and [third-party licensing](.github/docs/legal/THIRD_PARTY_LICENSES.md).
