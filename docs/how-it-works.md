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

The panel is a single process (a web server with a built-in scheduler) plus
one SQLite file. There is no external database, cache or message queue to run
or keep alive. A configured Telegram bot runs as a supervised subprocess next
to it. Each node runs its own API process and the OpenVPN daemon — one Docker
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
  nodes, login sessions, settings and audit log. WAL mode lets the scheduler
  write while you browse.
* **Node:** `/etc/openvpn/ovnode/users/<cn>/` holds one folder per user
  (display name, login limit, a disabled marker, cached `.ovpn`), plus session
  markers and usage counters. The PKI lives under `/etc/openvpn/server/`.

## Identity: one number per user

A user's numeric panel id *is* their OpenVPN common name: user 42 gets
certificate CN `42`. The node stores the display name alongside it, so usage
reports can be keyed by username while the certificate layer stays numeric.

## Security model

* **Secret URL path (URLPATH):** the panel is served under a random prefix
  (for example `/k3f9xq2m/`). Anything outside it gets an empty 404, so
  internet scanners see an empty site. It hides the panel; it is not login.
* **DB-backed sessions:** login returns an opaque random token; only its
  SHA-256 hash is stored. Sessions slide on activity and expire, logout
  deletes the row, and restarting the panel does not log everyone out.
* **Limits enforced on the node:** `max_logins` is pushed to every node and
  enforced there at connect time (1 = takeover, N = reject the N+1th, 0 =
  unlimited). The panel only aggregates session counts and can disconnect.

## The dashboard's live view

A background collector polls nodes every 10 seconds while a browser has the
live stream open, backing off to every 5 minutes when nobody is watching.
Handlers read its in-memory snapshot, so a dead node can never stall the user
list. Other jobs clean stale sessions, push limits to nodes, prune logs and
history, and send the daily expiry/quota summary to the owner.

## Updates

Run `ovmanager update` (or **Update** in the `ovmanager`/`ovm` terminal menu);
`install.sh update` does the same, and the database migrates automatically on
the next start. The same menu has start/stop/restart, logs, backup and TLS.

## Backup and restore

`ovmanager backup` tars the data directory into `/var/backups`. **Settings →
Backups** also creates a downloadable database copy and restores an upload
atomically: writes are refused (HTTP 503) until the swap finishes, the current
database is kept as a fallback, and the restored one is migrated on the spot.
