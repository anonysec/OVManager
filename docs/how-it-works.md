# How OVManager works

A plain-language tour of the moving parts — no programming knowledge needed.

## The big picture

OVManager is really two programs on two kinds of machine:

* **The panel** — the website you log into. It keeps the user list, quotas,
  expiry dates, settings and logs.
* **OVNode** — a small agent on every VPN server. It owns OpenVPN, the
  certificates, and the per-user files.

The panel always calls the node. **Nodes never call the panel**, so you can
move or replace the panel at any time without touching the VPN servers.

## What runs where

The panel is two processes and one SQLite file. The web server runs the live
collector and serves requests; a supervised child runs the periodic jobs
(traffic accounting, limit enforcement, backups, pruning, alerts), so a job
that blocks cannot stop the panel answering. Both are started and stopped by
the one service, and the child takes an exclusive lock on the data directory
so a second one cannot start and double every schedule.

Neither process runs as root. They are started by a systemd unit with
`User=ovmanager`, a dedicated unprivileged account: the web server reads its own
code, `.env` and TLS key through that account's group, and owns the data
directory the database lives in. The panel is reachable from the network and
parses untrusted input, so a compromise of the web app should not be a
compromise of the host. The consequence is that the panel cannot update itself
— replacing the tree and restarting the unit needs root — so the in-app update
button tells you to run `sudo ovm update` instead. (Docker has always run the
app as its own `appuser`, for the same reason.)

There is no external database, cache or message queue to run or keep alive. A
configured Telegram bot runs as a supervised subprocess next to them. Each node runs its own API process and the OpenVPN daemon — one Docker
container supervises both, natively they are separate services.

## How they talk

The panel connects out to each node and calls `/sync/...` endpoints. Every
request carries the node's API key in a `key` header, and every reply is a
small envelope:

```text
{"success": true, "msg": "...", "data": {...}}
```

TLS is verified strictly first. A node using a self-signed certificate (the
installer default) fails that check, so the panel retries once *without*
verification and warns loudly, once per node — a reminder to switch to Let's
Encrypt. The panel itself can also serve HTTPS either way.

## Traffic collection and billing

Every 5 minutes the panel asks each node for `/sync/usage`. The node reports a
**lifetime total** per user: bytes banked when sessions ended plus bytes still
flowing in live sessions. The panel remembers the last number it saw per node
and adds only the increase to the user's `used` counter — so short sessions,
disconnects and restarts never double-bill, and one that shrinks bills zero.

One node's whole payload is processed and then stored with a **single
database commit per tick**. Each user write is conditional, so if an admin
resets or deletes that user at the same moment the stale update becomes a
no-op. Quota crossings are enforced immediately after the tick; a separate
10-minute sweep catches expiry-only cases.

## Where the data lives

* **Panel:** `ovmanager.db` (SQLite) in the panel's data directory — users,
  nodes, login sessions, settings and audit log. WAL mode lets the jobs
  process write while you browse.
* **Node:** `/etc/openvpn/ovnode/users/<cn>/` holds one folder per user
  (display name, login limit, a disabled marker, cached `.ovpn`), plus session
  markers and usage counters. The PKI lives under `/etc/openvpn/server/`.

## Identity: one number per user

A user's numeric panel id *is* their OpenVPN common name: user 42 gets
certificate CN `42`. The node stores the display name alongside it, so usage
reports can be keyed by username while the certificate layer stays numeric.

Each user can also carry an optional free-text **tag** (up to 64 characters,
for example `monthly`, `vip`, `reseller-a`). It shows on the user row and is
searchable and filterable — a lightweight way to group customers without
adding any schema beyond one column.

## Security model

* **Credentials live in the database, not in `.env`.** The owner is an ordinary
  `admins` row; `ADMIN_USERNAME` in `.env` only says *which* row is the owner.
  Changing the owner password is `ovm reset-password`, and it writes the row.
  On upgrade from an older install the pre-existing `ADMIN_PASSWORD_HASH` is
  imported into that row once (schema v16), so nobody is locked out.
* **What the trust boundary actually is.** Secrets in the database — node API
  keys, the Telegram bot token — are stored as written; there is no at-rest
  encryption, by design (see `backend/db/crud/settings.py`). Encrypting them
  would only move the key to another file on the same host. What protects them
  is the filesystem, so these modes are load-bearing, not incidental: the data
  directory and backup directory are `0700`, and `ovmanager.db`,
  `node-certs/*.pem` and every `.ovmbak` bundle are `0600` (root-only).
  A backup bundle is a copy of the database: **treat any off-site copy as
  secret material** and move it over an encrypted channel.
* **Secret URL path (URLPATH):** the panel is served under a random prefix
  (for example `/k3f9xq2m/`). Anything outside it gets an empty 404, so
  internet scanners see an empty site. It hides the panel; it is not login.
* **DB-backed sessions:** login returns an opaque random token; only its
  SHA-256 hash is stored. Sessions slide on activity and expire, logout
  deletes the row, and restarting the panel does not log everyone out.
* **Limits enforced on the node:** `max_logins` is pushed to every node and
  enforced there at connect time (1 = takeover, N = reject the N+1th, 0 =
  unlimited). The panel only aggregates session counts and can disconnect.

## The design system

Every colour, space, radius, shadow and font in the dashboard comes from a
**design token** — a CSS custom property declared in exactly one file,
`frontend/src/tokens.css`. There are around 175 of them, and that file is the
only place allowed to declare `:root` or `html[data-theme=...]`; the rule is
enforced mechanically by `npm run check:tokens`, which fails the build if a
token block appears anywhere else.

The rule exists because of a real bug. `index.css` and `styles.css` once both
shipped a full palette, and because `main.jsx` imports `index.css` first,
`styles.css` silently won — leaving around sixteen of `index.css`'s tokens as
dead code. The mismatch is what forced eighty-odd `!important` declarations
elsewhere, each one a small admission that the cascade was no longer trusted.
One file means one winner.

Two consequences worth knowing:

- **Use semantic tokens, not hex.** A component asks for `var(--danger-text)`
  or `var(--space-3)`, never `#e5484d`. Both themes are then a palette swap in
  one file rather than a hunt through every stylesheet.
- **Both themes are declared side by side.** Dark is the default `:root`;
  light is a `html[data-theme="light"]` override in the same file, so a new
  token that forgets one theme is visible in review rather than on someone's
  screen.

The tooling around this is described under `frontend/scripts/`: `check-tokens.mjs`
also resolves the `var()` chain and asserts WCAG AA (4.5:1) contrast for the
text/background pairs that matter, in both themes.

## The dashboard's live view

A background collector polls nodes every 10 seconds while a browser has the
live stream open, backing off to every 5 minutes when nobody is watching.
Handlers read its in-memory snapshot, so a dead node can never stall the user
list. Other jobs clean stale sessions, push limits to nodes, prune logs and
history, and send the daily expiry/quota summary to the owner.

That same 5-minute collector watches whether each node answers its probe. On
the **transition** the panel can message the owner on Telegram — one "node is
unreachable" alert per outage, and one "back online" message when it answers
again; a flapping node is throttled so it cannot page you every 5 minutes.
The toggle (on by default) is **Settings → Alerts → "Node goes down or comes
back"**; it needs the bot token and owner ID from the Bot section. A failed
send (bot down, token changed) is retried on the next tick, so the alert
still lands once Telegram works again.

## Updates

Run `ovmanager update` (or **Update** in the `ovmanager`/`ovm` terminal menu);
`install.sh update` does the same, and the database migrates automatically on
the next start. The same menu has start/stop/restart, logs, backup and TLS.

## Backup and restore

`ovmanager backup` asks the panel to write a verified database bundle
(`.ovmbak`) into `/var/lib/ovmanager/backups` (newest 14 kept; `--keep N`
changes that), and `ovmanager auto-backup on` adds a daily systemd timer for
it. **Settings → Backup** can instead schedule database backups inside the
panel (off by default) and restores an upload atomically: writes are refused
(HTTP 503) until the swap finishes, the current database is kept as a
fallback, and the restored one is migrated on the spot.

Scheduled backups can also keep an **offsite copy**: fill in a target like
`backup@server:/backups/panel` and after each automatic backup the newest
file is pushed there with `rsync` (or `scp` when rsync is missing). The
transfer uses plain SSH with key-based login (`BatchMode`, no password
prompts), so the target machine must accept your key and the target folder
must already exist. Success or failure is written to the Audit Log — nothing
else on the remote side is touched or cleaned up.
