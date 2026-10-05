# OVManager

Web panel for a self-hosted VPN service: users, traffic quotas, expiry dates, device limits and live sessions, across one server or many.

<div align="center">
  <img src=".github/assets/banner.svg" alt="OVManager — self-hosted OpenVPN control panel" width="820">
  <br><br>

  [![Version](https://img.shields.io/badge/version-1.0.45-blue)](CHANGELOG.md)
  [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
  [![CI](https://github.com/anonysec/OVManager/actions/workflows/ci.yml/badge.svg)](https://github.com/anonysec/OVManager/actions/workflows/ci.yml)
  [![Python](https://img.shields.io/badge/python-3.12%2B-3776ab?logo=python&logoColor=white)](pyproject.toml)
  [![React](https://img.shields.io/badge/react-19-087ea4?logo=react&logoColor=white)](frontend/package.json)
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
- **Updates that undo themselves.** `sudo ovm update` downloads a verified release, stages it, health-checks the new version, and automatically restores the previous code if the panel does not come up. `sudo ovm rollback` does the same thing by hand.
- **Nothing is compiled on your server.** The installer downloads a signed-off release archive plus its mandatory SHA-256 sidecar and refuses to continue if the download is not a real archive or the checksum does not match. No compiler, no `git`, no `npm` on the box.
- **The VPN servers are independent of the panel.** Nodes never call the panel and do not store its address, so the panel can be moved, rebuilt or replaced without touching a single VPN server. Re-attach them with the same address, name and key.
- **Limits that hold while the panel is down.** The device limit is pushed to each node and enforced there at connect time. The panel is not asked permission, and its absence changes nothing.
- **Accounting that cannot double-bill.** Each node reports a lifetime byte total per user; the panel remembers the last number it saw and bills only the increase. A dropped session, a restart or a rebuilt node cannot over-count.
- **A bot, if you want one.** Status, user actions and alerts from Telegram, off until you add a token.
- **A real API underneath.** The dashboard is a client of the panel's own JSON API, which speaks the same login session. FastAPI will serve the OpenAPI schema at `/doc` when you set `DOC=True` in `.env` — it is off by default.

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
- Warnings from 80% of quota, and a daily Telegram summary of users expiring within three days and users out of traffic.
- Device limits enforced on the node, from 1 (a new connection takes over) through N (the N+1th is rejected) to 0 (unlimited).

### 🌐 Nodes
- Add a node with an address, port and API key, or paste its `ovnode://` bundle and let the form fill itself in.
- Test connection before saving; the node row then shows reachability, agent and OpenVPN version, and session counts.
- Per-node settings pushed from the panel: DNS servers, IPv6 pool and prefix, extra OpenVPN ports.
- Node-down and node-recovered alerts over Telegram, throttled so a flapping node cannot page you every five minutes.
- `2083` is the only port the panel needs; the node agent is installed by its own one-liner.

### 🔐 Security and TLS
- Login sessions are opaque tokens in the database, stored as a SHA-256 hash, sliding on activity and revocable per account.
- Rate limits on failed logins, per username and per address, with a `Retry-After` on the claim endpoint.
- The panel is served under a random secret URL prefix; anything outside it gets an empty 404, so scanners see nothing.
- Self-signed, Let's Encrypt (domain or IP) or your own key and certificate, switchable from the CLI or from Settings → TLS.
- Node connections verify TLS strictly first and warn once per node when a self-signed certificate forces a fallback.
- Secrets live in the database, not in `.env`; the data directory is `0700` and the database and every backup bundle are `0600`.
- A filterable audit log of who changed what, exportable as CSV.

### 🤖 Automation and API
- Telegram bot: browse, create, edit, extend and delete users, pick a node for a config, inspect nodes and status, choose the bot's language, and receive alerts — from the phone.
- Scheduled backups inside the panel or through a systemd timer, with an optional off-site copy pushed to your own SSH host.
- A daily systemd timer that keeps running even when the panel is stopped.
- Public subscription endpoint that answers with a page, a usage summary or the `.ovpn` itself.

### 🔧 Operations
- `ovm doctor` runs 13 health checks over the service, autostart, file modes, data directory, disk space, worker, HTTP health and certificate; `--fix` applies the safe ones.
- Staged updates with automatic failover, `ovm rollback` for the previous code tree, and `ovm recover-update` for an update interrupted by a reboot.
- Verified `.ovmbak` backup bundles, listed and restored by name, or uploaded and restored atomically from the panel.
- Uninstall keeps your data unless you pass `--purge`; purging takes a snapshot to `/var/backups` first.
- A text menu for everything above — run `ovmanager` with no arguments.

## 🚀 Install

**Before you start:**

- A Linux server — Debian or Ubuntu recommended.
- Root, or an account with `sudo`.
- For the default native install, a host with systemd. On WSL, or in a container without systemd, use Docker mode instead.
- Port `2095` free. Port `80` free too if you intend to use Let's Encrypt during the install.
- Nothing else. The installer brings its own Python runtime; `git`, `npm` and Docker are not required.

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
```

This is the interactive install. Run with no flags it asks, and given no terminal it stops and tells you to pass `--yes` rather than choosing for you.

The menu offers **Install** (recommended, asks nothing else) and **Install with Docker**. To answer every setting yourself, run the wizard instead:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) interactive
```

**With no terminal** — a run without one cannot ask, so it needs `--yes` to say that is intended:

```bash
curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh \
  | sudo bash -s -- --yes

curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh \
  | sudo bash -s -- --docker --yes
```

The installer takes exactly three flags — `-y/--yes`, `--docker`, `-h/--help`. Everything else is an `OVM_*` variable, and each one is also the wizard's default, so a scripted run and an interactive one cannot disagree:

| Variable | Values |
| --- | --- |
| `OVM_PORT` | Panel port (default `2095`) |
| `OVM_PATH` | Secret URL prefix: `random` (default), `root`, or a name |
| `OVM_ADMIN_USER` | Owner login name (default `admin`) |
| `OVM_TLS` | `self` (default), `le`, `le-ip`, `custom` |
| `OVM_TLS_DOMAIN`, `OVM_TLS_KEY`, `OVM_TLS_CERT` | For `le` and `custom` |
| `OVM_PUBLIC_URL` | Address used in subscription links, when it cannot be inferred |
| `OVM_MODE` | `native` or `docker` |
| `OVM_VERSION` | Pin an install or update to one release |
| `OVM_REPO` | `myorg/OVManager` to install and update from a fork |

`CI=true` implies `--yes`. The older flag spellings (`-p/--pass`, `--mode`, `--tls*`, `-i`) still work and each prints what replaces it. The installer's own commands are `update`, `uninstall`, `interactive`, `version-script` and `help`; with none given it installs. `bash install.sh --help` prints the whole surface.

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
| `/opt/ovmanager` | The installed tree, with its own virtualenv |
| `/opt/ovmanager/.env` | Configuration — port, URL prefix, public URL, TLS paths |
| `/var/lib/ovmanager` | The database and the backup bundles |
| `/etc/ssl/self-signed` | The installer's self-signed pair, shared with the node installer |

**Then attach a server.** The panel manages accounts; it does not carry VPN traffic. Install OVNode on the machine your users will connect to and register it under **Nodes → Add Node** — the panel's Ready card prints a ready-to-paste command with the API key already filled in. Until a node is green, the panel has nothing to hand out.

**Managing it afterwards** is `ovm` (alias `ovmanager`), installed on the server and refreshed by every update. Run it bare for a menu: Status · Start/Stop/Restart · Logs · Backup · Auto backup · Update · TLS · Recovery · Uninstall.

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
| `sudo ovm doctor [--fix]` | Run the health checks; `--fix` applies the safe repairs. |
| `sudo ovm logs [N\|-f]` | Last N log lines (default 100), or follow live. |
| `sudo ovm start \| stop \| restart` | Service control. `enable` / `disable` set automatic start. |
| `sudo ovm backup [--keep N]` | Write a verified backup now. `--keep` is 1–500, default 14. |
| `sudo ovm restore [NAME]` | List backups, or restore one by name. |
| `sudo ovm auto-backup on \| off` | Daily backup through a systemd timer (`--time HH:MM`, `--keep N`). |
| `sudo ovm https` | `--self`, `--domain NAME`, `--ip`, or `--key F --cert F`. |
| `sudo ovm tls-status` | The installed certificate and when it expires. Read-only. |
| `sudo ovm update` | Staged update with automatic failover. |
| `sudo ovm rollback` | Restore the newest pre-update code snapshot. |
| `sudo ovm recover-update` | Recover an update interrupted by a reboot or power loss. |
| `sudo ovm owner-claim` | Print a fresh one-time claim key, before the panel has been claimed. |
| `sudo ovm reset-password` | Set a new owner password, then restart the panel. |
| `sudo ovm reset-urlpath` | Clear the secret panel URL prefix. |
| `sudo ovm recovery` | Reprint the panel URL and login name. Read-only. |
| `sudo ovm uninstall [--purge]` | Remove the app. Data is kept unless `--purge`. |
| `sudo ovm completion` | Install bash completion. |

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
