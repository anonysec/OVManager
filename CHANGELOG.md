# Changelog

## 1.0.0 — 2026-09-29

First public release.

**Install**

- One installer for both modes: native (systemd) or Docker, with safe defaults
  and no questions.
- Three flags, `-y/--yes`, `--docker` and `-h/--help`. Everything else is an
  `OVM_*` variable, so a scripted install and a wizard install produce the same
  configuration. Older spellings still work and say what replaces them.
- Installs a verified release archive and checks its published checksum. Nothing
  is built on your server.
- TLS is always on: self-signed by default, Let's Encrypt or your own
  certificate if you prefer. The self-signed browser warning is named in the
  summary rather than hidden.

**First login**

- The installer mints no owner password. It prints a one-time claim key, and you
  open the printed URL and choose the password in the browser.
- The password is stored as a bcrypt hash in the panel database, never in `.env`.
- The key is single-use and rate-limited. Lost it before claiming?
  `ovm owner-claim` prints a new one.

**The panel**

- Users with a traffic quota, an expiry date and a device limit that holds at
  connect time, on the node.
- Traffic is read from each node's lifetime totals every five minutes and only
  the increase is billed, so restarts and disconnects cannot double-count.
- Subscription links and per-user `.ovpn` downloads.
- Any number of VPN nodes, with live health, session counts and per-node DNS,
  IPv6 and extra ports.
- Backups now, on a schedule, off-site over SSH, or into Telegram. Restores are
  atomic and keep the previous database as a fallback.
- A secret URL prefix for the panel, an audit log, extra admin accounts, and a
  Telegram bot (off by default). Available in English, Persian, Russian and
  Chinese.

**Managing it**

- `ovm status`, `ovm doctor [--fix]`, `ovm start|stop|restart`, `ovm logs`,
  `ovm backup`, `ovm restore`, `ovm https`, `ovm tls-status`, `ovm recovery`,
  `ovm update`, `ovm rollback`, `ovm recover-update`, `ovm reset-password`,
  `ovm reset-urlpath`, `ovm owner-claim`, `ovm completion`, `ovm version-script`,
  `ovm uninstall [--purge]`.
- Updates download and verify the release, stage it, and roll back automatically
  if the new version does not come up. The database migrates on the next start.
- Uninstall keeps your data. `--purge` takes a snapshot first, then deletes it.
