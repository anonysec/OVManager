# OVManager roadmap

> Status: all six steps shipped in **2.1.0** (2026-09-17).

Plain-language plan for making the project clean, fast, simple to use, and
modern. Customer-facing safety and billing correctness come first.

## Step 1 — Reliability fixes (current interface)

- Traffic counting: the background collector writes once per run, uses
  conditional updates so a reset/delete cannot be silently overwritten, and
  never double-bills a delta after a crash.
- Deleting/revoking a user is reliable, including a retried delete
  (certificate revocation list is regenerated).
- Passwords and private keys are never briefly world-readable during install
  or file generation; installer backups are private.
- Login lockout cannot be bypassed with a spoofed `X-Forwarded-For` behind
  nginx/caddy.
- Changing an admin password ends that admin's live sessions.
- An expired or out-of-traffic user cannot be re-activated by a status toggle.
- Wrong addresses under a secret panel path return a normal 404 (blank body),
  not an odd empty 200.
- Slow work (geolocation, backups/restores) no longer freezes the panel.
- Node login limits are only changed when the panel actually sends one.

## Step 2 — Installers and terminal menus

- Both installers get a start menu: `Express / Custom / Update / Uninstall`.
- TLS is always on: `self-signed` (default) / `Let's Encrypt` (domain or IP) /
  `custom` key + cert paths. Plain HTTP is rejected.
- End of panel install asks: install a VPN node on this same server too?
  Default No; Express auto-registers it, Custom asks.
- `ovmanager` / `ovm` (panel) and `ovnode` / `ovn` (node) terminal menus:
  status, start/stop/restart, logs, backup, update, TLS, recovery, uninstall.
  Fancy boxes when `whiptail` is present, colored menu otherwise.

## Step 3 — Full panel redesign

- New design system, mobile-first; Home · Users · Nodes · Health · Settings.
- Customer subscription page redesign and first-login wizard.
- Node Advanced settings (DNS, IPv6, extra ports) with Apply, rollback on
  failure, OpenVPN/agent version display and update.
- Admins page for the owner (enable/disable, sign out all devices), admin
  dashboard with their own stats and action history.

## Step 4 — Speed and light footprint

- One database write per traffic tick; heavy jobs off the request path.
- Leaner Docker image; SQLite stays; stress test at 100–1,000 users.

## Step 5 — Modern touches

- Panel-only Telegram bot (off by default, button-first, role-aware).
- PWA phone install, one-click updates for panel and nodes, auto theme,
  expiry/traffic alerts.

## Step 6 — Cleanup, docs, release

- Remove dead/duplicate code, consistent naming, beginner docs, owner
  password recovery command, changelogs, fresh-machine tests.
