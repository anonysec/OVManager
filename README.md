# OVManager

Web panel for a self-hosted VPN service: users, traffic quotas, expiry dates, device limits and live sessions, across one server or many.

<div align="center">
  <img src=".github/assets/banner.svg" alt="OVManager — self-hosted OpenVPN control panel" width="820">
  <br><br>

  [![Version](https://img.shields.io/badge/version-2.4.6-blue)](CHANGELOG.md)
  [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
  [![CI](https://github.com/anonysec/OVManager/actions/workflows/ci.yml/badge.svg)](https://github.com/anonysec/OVManager/actions/workflows/ci.yml)
  [![Go](https://img.shields.io/badge/go-1.27+-00ADD8?logo=go&logoColor=white)](go.mod)
  [![React](https://img.shields.io/badge/react-19-087ea4?logo=react&logoColor=white)](web/package.json)
  [![Runtime](https://img.shields.io/badge/runtime-systemd%20%7C%20docker-555555)](#-install)
</div>

> Full documentation: https://anonysec.github.io/OVManager/


## Project Status

> **Early Development / Proof of Concept**
>
> This repository is currently an early-stage proof of concept. It is not production-ready, APIs and configuration formats may change, and operational guarantees are limited. Use in test environments only.

## Tech Stack

- Go
- Linux (Ubuntu)
- OpenVPN
- RADIUS
- iptables
- systemd

## Roadmap

- Core Go refactor of legacy shell-based workflows
- API implementation for node, user, session, and accounting operations
- Security auditing and hardening of authentication, TLS, and filesystem access
- Concurrency and routing logic improvements
- Documentation and operator CLI polish
- Community release and packaging

## Upcoming Architecture

The project is preparing for a major architectural refactor. Advanced AI-assisted development will be used to improve concurrent routing logic, strengthen security checks, and accelerate the transition from proof-of-concept scripts to a robust, production-oriented management platform. This phase will focus on safer defaults, clearer module boundaries, and more reliable operational behavior across OpenVPN and RADIUS-integrated environments.

## 📖 Table of contents

- [What is this?](#-what-is-this)
- [Why this one?](#-why-this-one)
- [Features](#-features)
- [Install](#-install)
- [After it finishes](#-after-it-finishes)
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
- **Updates that undo themselves.** `sudo ovmanager update` downloads a verified release, stages it, health-checks the new version, and automatically restores the previous code if the panel does not come up.
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
- Subscription UUID URLs act as bearer links outside the secret panel path, so they can be shared — with a QR code for phone clients.
- Additional admin accounts alongside the owner, each of which can be enabled or disabled, with their own sessions listed and revocable.

### 📊 Traffic accounting
- Usage collected every five minutes from every node, counted as the increase over the last reading — short sessions, disconnects and restarts cannot double-count, and a total that shrinks bills zero.
- Quota crossings enforced immediately after the tick that detects them; expiry-only cases caught by a separate ten-minute sweep.
- Conditional database writes, so an admin action landing mid-tick becomes a no-op rather than being overwritten by stale data.
- If a legacy numeric username collides with another user’s numeric ID, accounting for those users on that node is deferred and a warning is recorded until the ambiguity is resolved; neither account is charged by guessing.
- Warnings from 80% of quota, caught at the tick that detects them.
- Device limits enforced on the node, from 1 (a new connection takes over) through N (the N+1th is rejected) to 0 (unlimited).

### 🌐 Nodes
- Add a node with an address, port and API key, or paste its `the node installer output` bundle and let the form fill itself in.
- Test connection before saving; the node row then shows reachability, agent and OpenVPN version, and session counts.
- Per-node settings pushed from the panel: DNS servers, IPv6 pool and prefix, extra OpenVPN ports.
- Deleting a panel user also deletes them on every reachable node, so no ghost sessions survive the panel row.
- `2095` is the only port the panel needs; the node agent is installed by its own one-liner.

### 🔐 Security and TLS
- Login sessions are opaque tokens in the database, stored as a SHA-256 hash, sliding on activity and revocable per account.
- Rate limits on failed logins, per username and per address, with a `Retry-After` on the claim endpoint.
- The panel UI is served under a random secret URL prefix; unrelated paths show a decoy 404. `/api/` and `/health` remain fixed routes; protected operations still require authentication.
- Strict security headers on every response (CSP, `X-Frame-Options: DENY`, nosniff), with HSTS added when the connection is TLS.
- Terminate HTTPS at a fronting proxy (nginx/Caddy) or set `SSL_CERTFILE`/`SSL_KEYFILE` in `.env`; `ovmanager tls` opens the interactive TLS menu (status, issue, renew, remove, self-signed, custom install).
- Built-in Let's Encrypt issues over HTTP-01. Port 80 must be reachable for ~60 seconds while the certificate is issued; if something else (nginx/apache/caddy) is bound to port 80, `ovmanager tls issue <domain>` offers to stop it temporarily (with confirmation) and restart it afterwards. Renewals happen automatically (T-30 days) via the `ovmanager-acme-renew.timer`. Issuance never needs an API key or DNS provider.
- Node connections verify TLS strictly first and warn once per node when a self-signed certificate forces a fallback.
- Secrets live in the database, not in `.env`; the data directory is `0700` and the database and every backup bundle are `0600`.
- A filterable audit log of who changed what, exportable as CSV.

### 🤖 Automation and API
- Backup scheduler: the installer writes a daily systemd timer (`ovmanager-backup.timer`) that runs a verified backup and prunes to 7 copies, whether or not the panel process is up.
- Public subscription endpoint that answers with a page, a usage summary or the `.ovpn` itself with `no-store` caching protection.
- Authenticated REST API supporting both durable UUIDs and compact numeric-ID aliases (`/api/users/id/{id}/...`, `/api/nodes/ovpn/id/{user_id}/{node_id}`) for operator automation, with full backward compatibility.
- Real-time Server-Sent Events stream (`/api/live/stream`) with scoped domain invalidations across user and node fleet state changes.
- Staged updates and every manual-verifying step are fully scripted.

### 🔧 Operations
- Staged updates with automatic failover; an update interrupted by a reboot is recovered on the next `ovmanager update` run.
- Verified `.db` backups, listed and restored by name (`ovmanager backup --keep N`, `ovmanager restore`).
- A bare `ovmanager` run prints the available screens and exits; every command has `--help`.

## 🚀 Install

**Before you start:**

- A Linux server — Debian or Ubuntu recommended.
- Root, or an account with `sudo`.
- A host with systemd.
- Port `2095` free.

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/v2.4.6/install.sh)
```

The installer defaults to Docker; use `--native` to install the verified release binary as a systemd service with a daily backup timer. Both paths start and health-check the panel. Use `interactive` or `--interactive` to configure it and optionally install OVNode on the same server; `-y` skips prompts. The panel URL and claim key are shown after the optional node installer and before following logs. `bash install.sh --help` prints the full surface.

If a previous failed OVNode attempt left `/opt/ovnode` behind, the node installer may treat that directory as an existing installation. Inspect it before retrying; do not remove it if it contains an existing node's configuration or data.

The command above pulls `install.sh` from the tagged release (v2.3.0, matching the binary's version constant), not from `main`, so a `main` change cannot silently change what root executes. The binary's SHA-256 is verified at install time against the sidecar shipped with that release; the installer script itself is not separately checksum-verified — there is no published sidecar for it, so only the binary's integrity is checked.

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

**First login.** Open the URL, paste the key, and choose the owner password — at least 8 characters, and not a placeholder like `change-me`. No password exists until you do this. On a panel nobody has claimed yet, that address shows the claim form; once claimed, the same address is the setup checklist. The key is spent the moment it works, and the password is stored as a bcrypt hash in the panel database, never in `.env`. Lost the key before claiming? `sudo ovmanager owner-claim` prints a fresh one. Claimed already and lost the password? `sudo ovmanager reset-password`.

**Where things live:**

| Path | What |
| --- | --- |
| `/opt/ovmanager` | The installed tree: the binary (with the dashboard inside), `.env` |
| `/opt/ovmanager/.env` | Configuration — port, data dir, owner login name |
| `/var/lib/ovmanager` | The database, backups and node material (mode `0700`) |
| `/usr/local/bin/ovmanager` | Symlink to the binary — the operator CLI |
| `.github/site` | Not on disk: the docs are the Pages site below |

**Then attach a server.** The panel manages accounts; it does not carry VPN traffic. Install OVNode on the machine your users will connect to and register it under **Nodes → Add Node** — the panel's Ready card prints a ready-to-paste command with the API key already filled in. Until a node is green, the panel has nothing to hand out.

**Managing it afterwards** is `ovmanager`, a symlink to the same binary that serves the panel. Run it bare for a command list, or `--help` per command. There is no `uninstall` command: stop the service and remove `/opt/ovmanager` and `/var/lib/ovmanager` (data is kept unless you remove it).

| What | How |
| --- | --- |
| Status, health, version, URL | `sudo ovmanager status [--all]` |
| Service control | `sudo ovmanager service start \| stop \| restart \| enable \| disable` |
| Server logs | `sudo ovmanager logs [N\|-f]` |
| Backup now (verified, pruned) | `sudo ovmanager backup [--keep N]` — default 14 |
| List backups, or restore | `sudo ovmanager restore [NAME]` |
| The daily timer | written by the installer; runs `ovmanager backup --keep 7` daily |
| Panel URL prefix | `sudo ovmanager urlpath` |
| TLS (interactive menu) | `sudo ovmanager tls` |
| Staged update with failover | `sudo ovmanager update` |
| Reset the owner password | `sudo ovmanager reset-password` |
| Shell completion | `sudo ovmanager completion bash\|zsh\|fish` |

## 🧰 Day-to-day commands

Every `ovmanager` command needs root, because each one reads the panel's `.env` to find the panel URL path and the install layout. The panel itself does not: any account can log in through the browser.

| Command | What it does |
| --- | --- |
| `sudo ovmanager status` | Service, health, version and panel URL. `--all` adds mode, port, data and install paths. |
| `sudo ovmanager logs [N\|-f]` | Last N log lines (default 100), or follow live. |
| `sudo ovmanager service start \| stop \| restart` | Service control. `enable` / `disable` set automatic start. |
| `sudo ovmanager backup [--keep N]` | Write a verified backup now. `--keep` is 1–500, default 14. The installer's daily timer pins `--keep 7`. |
| `sudo ovmanager restore [NAME]` | List backups, or restore one by name. |
| `sudo ovmanager urlpath` | Print the secret URL prefix the panel is served under. |
| `sudo ovmanager tls` | Interactive TLS menu: status, issue Let's Encrypt, self-signed, install a custom cert, renew, remove. |
| `sudo ovmanager update` | Staged update with automatic failover; recovers an interrupted update first. |
| `sudo ovmanager reset-password` | Set a new owner password, then restart the panel. |
| `sudo ovmanager completion` | Install shell completion (`bash\|zsh\|fish\|powershell`). |

`ovmanager update` covers rollback too: the pre-update tree is kept, `ovmanager restore` restores backups, and an update interrupted mid-flight is recovered automatically at the next `ovmanager update` call.

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
| [CLI reference](https://anonysec.github.io/OVManager/wiki/cli.html) | Every `ovmanager` and `ovnode` command, the installer's flags, and the `OVM_*` settings. |

Elsewhere in this repository:

- [CONTRIBUTING.md](.github/CONTRIBUTING.md) — ground rules, manual install, the checks, release freeze.
- [SECURITY.md](SECURITY.md) — how to report a vulnerability.
- [CHANGELOG.md](CHANGELOG.md) — what changed in each release.

## 📄 License

MIT. Free for personal and commercial use: no license server, no paid feature gate, no node or user limit. Keep the copyright and MIT license notice with copies or substantial portions of the software.

**You operate the VPN.** Abuse complaints (spam, scanning, copyright) come to you, not to this project. Enforce per-user quotas and expiry, watch the connection events in the audit log, disable abusers promptly, and respect your provider's terms of service and local law.

See [Privacy](.github/docs/legal/PRIVACY.md), [Acceptable use](.github/docs/legal/ACCEPTABLE_USE.md), [Trademarks](.github/docs/legal/TRADEMARKS.md) and [third-party licensing](.github/docs/legal/THIRD_PARTY_LICENSES.md).

## Dev builds
Install a rolling dev build: `OVM_VERSION=dev bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)`. Dev versions look like `dev-YYYYMMDD.N-<sha>`.
