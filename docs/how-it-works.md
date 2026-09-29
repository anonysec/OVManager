# How OVManager works

A plain-language tour of the moving parts. No programming knowledge needed.

## The big picture

OVManager is two programs on two kinds of machine:

* **The panel** — the website you log into. It keeps the user list, quotas,
  expiry dates, settings and logs.
* **OVNode** — a small agent on every VPN server. It owns OpenVPN, the
  certificates and the per-user files.

The panel always calls the node. **Nodes never call the panel**, so you can move
or replace the panel at any time without touching the VPN servers.

## What runs where

The panel is two processes and one SQLite file. The web server runs the live
collector and serves requests. A supervised child runs the periodic jobs
(traffic accounting, limit enforcement, backups, pruning, alerts), so a job that
blocks cannot stop the panel answering. Both are started and stopped by the one
service, and the child takes an exclusive lock on the data directory so a second
one cannot start and double every schedule.

Neither process runs as root. A systemd unit starts them as `ovmanager`, a
dedicated unprivileged account: the web server reads its own code, `.env` and the
TLS key through that account's group, and owns the data directory the database
lives in. The panel is reachable from the network and parses untrusted input, so
a compromise of the web app should not be a compromise of the host. The
consequence is that the panel cannot update itself — replacing the tree and
restarting the unit needs root — so the update button in the UI prints
`sudo ovm update` instead. Docker has always run the app as its own `appuser`,
for the same reason.

There is no external database, cache or message queue to run or keep alive. A
configured Telegram bot runs as a supervised subprocess next to the two
processes. Each node runs its own API process and the OpenVPN daemon: one Docker
container supervises both, natively they are separate services.

**Why not Redis.** It is the right answer when several application processes must
share cache or pub/sub state. Here the web process is the only reader of the live
cache and the children do not share it — they coordinate through SQLite, which is
already the source of truth — so a Redis hop would only add latency, a second
thing to run and back up, and roughly 10 to 30 MB of resident memory. It becomes
worthwhile only if the panel moves to multiple *web* workers, which would mean
replacing SQLite with a networked database first.

What is done instead:

- One background collector polls the nodes and caches the result. Request
  handlers read that cache instead of fanning out to every node per request.
- The collector backs off to `OVMANAGER_LIVE_IDLE_POLL_SECONDS` (default 300s)
  when no browser has the live stream open, rather than probing every node every
  10 seconds for an audience of nobody.
- Security-header and CSRF handling are plain ASGI middlewares, so requests do
  not pay for Starlette's `BaseHTTPMiddleware` task-and-queue wrapper, which also
  keeps the SSE stream unbuffered.
- The built `index.html` is cached in memory and invalidated by mtime, so serving
  an SPA route is one `stat()` rather than a file read per navigation.

## How they talk

The panel connects out to each node and calls its `/sync/...` endpoints. Every
request carries the node's API key in a `key` header, and every reply is a small
envelope:

```text
{"success": true, "msg": "...", "data": {...}}
```

TLS is verified strictly first. A node using a self-signed certificate (the
installer default) fails that check, so the panel retries once *without*
verification and warns loudly, once per node, as a reminder to switch to Let's
Encrypt. The panel itself can serve HTTPS either way.

## Traffic collection and billing

Every 5 minutes the panel asks each node for `/sync/usage`. The node reports a
**lifetime total** per user: bytes banked when sessions ended plus bytes still
flowing in live sessions. The panel remembers the last number it saw per node and
adds only the increase to the user's `used` counter, so short sessions,
disconnects and restarts never double-bill, and a total that shrinks bills zero.

One node's whole payload is processed and then stored with a **single database
commit per tick**. Each user write is conditional, so if an admin resets or
deletes that user at the same moment, the stale update becomes a no-op. Quota
crossings are enforced immediately after the tick; a separate 10-minute sweep
catches expiry-only cases.

## Where the data lives

* **Panel:** `ovmanager.db` (SQLite) in the panel's data directory —
  `/var/lib/ovmanager` on a native install: users, nodes, login sessions,
  settings and the audit log. WAL mode lets the jobs process write while you
  browse.
* **Node:** `/etc/openvpn/ovnode/users/<cn>/` holds one folder per user (display
  name, login limit, a disabled marker, cached `.ovpn`), plus session markers and
  usage counters. The PKI lives under `/etc/openvpn/server/`.

## Identity: one number per user

A user's numeric panel id *is* their OpenVPN common name: user 42 gets
certificate CN `42`. The node stores the display name alongside it, so usage
reports can be keyed by username while the certificate layer stays numeric.

Each user can also carry an optional free-text **tag** (up to 64 characters, for
example `monthly`, `vip`, `reseller-a`). It shows on the user row and is
searchable and filterable, which groups customers without adding anything beyond
one column.

## Security model

* **Credentials live in the database, not in `.env`.** The owner is an ordinary
  `admins` row; `ADMIN_USERNAME` in `.env` only says *which* row is the owner.
  Changing the owner password is `ovm reset-password`, and it writes that row. On
  upgrade from an older install the pre-existing `ADMIN_PASSWORD_HASH` is
  imported into the row once (schema v16), so nobody is locked out. The panel now
  ignores both of those `.env` lines and logs a warning when it sees them.
* **The trust boundary is the filesystem.** Secrets in the database — node API
  keys, the Telegram bot token — are stored as written; there is no at-rest
  encryption, by design (see `backend/db/crud/settings.py`). Encrypting them
  would only move the key to another file on the same host. What protects them is
  the file modes, so these are load-bearing, not incidental: the data directory
  and backup directory are `0700`, and `ovmanager.db`, `node-certs/*.pem` and
  every `.ovmbak` bundle are `0600`. A backup bundle is a copy of the database:
  **treat any off-site copy as secret material** and move it over an encrypted
  channel.
* **Secret URL path (URLPATH):** the panel is served under a random prefix, for
  example `/k3f9xq2m/`. Anything outside it gets an empty 404, so internet
  scanners see an empty site. It hides the panel; it is not login.
* **Database-backed sessions:** login returns an opaque random token and only its
  SHA-256 hash is stored. Sessions slide on activity and expire, logout deletes
  the row, and restarting the panel does not log everyone out.
* **Limits enforced on the node:** `max_logins` is pushed to every node and
  enforced there at connect time (1 = takeover, N = reject the N+1th, 0 =
  unlimited). The panel only aggregates session counts, and can disconnect.

## The design system

Every colour, space, radius, shadow and font in the dashboard comes from a
**design token**, a CSS custom property declared in exactly one file,
`frontend/src/tokens.css`. There are around 180 of them, and that file is the
only place allowed to declare `:root` or `html[data-theme=...]`. The rule is
enforced mechanically by `npm run check:tokens`, which fails the build if a token
block appears anywhere else.

The rule exists because of a real bug. `index.css` and `styles.css` once both
shipped a full palette, and because `main.jsx` imports `index.css` first,
`styles.css` silently won, leaving around sixteen of `index.css`'s tokens as dead
code. The mismatch is what forced eighty-odd `!important` declarations
elsewhere, each one a small admission that the cascade was no longer trusted. One
file means one winner.

Two consequences worth knowing:

- **Use semantic tokens, not hex.** A component asks for `var(--danger-text)` or
  `var(--space-3)`, never `#e5484d`. Both themes are then a palette swap in one
  file rather than a hunt through every stylesheet.
- **Both themes are declared side by side.** Dark is the default `:root`; light
  is a `html[data-theme="light"]` override in the same file, so a new token that
  forgets one theme is visible in review rather than on someone's screen.

`frontend/scripts/check-tokens.mjs` also resolves the `var()` chain and asserts
WCAG AA (4.5:1) contrast for the text/background pairs that matter, in both
themes.

## The dashboard's live view

A background collector polls nodes every 10 seconds while a browser has the live
stream open, backing off to every 5 minutes when nobody is watching. Handlers
read its in-memory snapshot, so a dead node can never stall the user list. Other
jobs clean stale sessions, push limits to nodes, prune logs and history, and send
the daily expiry and quota summary to the owner.

That same 5-minute collector watches whether each node answers its probe. On the
**transition** the panel can message the owner on Telegram: one "node is
unreachable" alert per outage, and one "back online" message when it answers
again. A flapping node is throttled so it cannot page you every 5 minutes. The
toggle (on by default) is **Settings → Alerts → "Node goes down or comes back"**,
and it needs the bot token and owner ID from the Bot section. A failed send (bot
down, token changed) is retried on the next tick, so the alert still lands once
Telegram works again.

## Updates

`sudo ovm update` updates the panel, and `install.sh update` does the same. The
new version is downloaded as a verified release archive, checked against its
published checksum, staged, and health-checked; if it does not answer, the
previous version is restored. The database migrates automatically on the next
start. An update interrupted mid-flight (power loss, reboot) is cleaned up by
`sudo ovm recover-update`, and the previous code tree is available as
`sudo ovm rollback`.

## Backup and restore

`sudo ovm backup` asks the panel to write a verified database bundle (`.ovmbak`)
into `/var/lib/ovmanager/backups` (newest 14 kept; `--keep N` changes that), and
`sudo ovm auto-backup on` adds a daily systemd timer for it. **Settings → Backup**
can instead schedule database backups inside the panel (off by default). A
restore from an upload is atomic: writes are refused with HTTP 503 until the swap
finishes, the current database is kept as a fallback, and the restored one is
migrated on the spot.

Scheduled backups can also keep an **off-site copy**: fill in a target like
`backup@server:/backups/panel` and after each automatic backup the newest file is
pushed there with `rsync` (or `scp` when rsync is missing). The transfer uses
plain SSH with key-based login (`BatchMode`, no password prompts), so the target
machine must accept your key and the target folder must already exist. Success or
failure is written to the audit log. Nothing else on the remote side is touched
or cleaned up.

## Container image

The `Dockerfile` is three stages, and the split is the point: the runtime image
should carry nothing a running panel does not need.

1. **`frontend`** (`node:22-slim`) builds the SPA. Node never reaches the runtime
   stage.
2. **`builder`** (`python:3.12-slim`) installs `uv` and runs
   `uv sync --frozen --no-dev`, which fails closed if `pyproject.toml` and
   `uv.lock` have drifted apart. `gcc` is installed here and only here: it is
   needed to build wheels, and it never reaches the runtime image.
3. **`runtime`** (`python:3.12-slim`) ships the venv, the sources and the
   frontend build. No compiler, no `uv`, no build tooling.

It runs as a non-root `appuser` in the `ovpanel` group (gid 997), which is what
lets the container read the config bind-mounted at `/app/.env`. The installer
refuses a gid that already has members on the host, because sharing that file by
group would hand the secret panel URL path to them.

## Schema migrations

The database is migrated automatically on every start. The current version is
recorded in a `schema_version` table, so numbered steps run once and in order:

```bash
uv run python -m backend.db.migrations --check    # CI drift gate
uv run python -m backend.db.migrations --migrate  # apply to the live database
```

Databases created by an earlier release are **adopted**: their current shape is
inspected, missing columns are added, and the database is then stamped at the
current version. No dump and restore is needed. `backend/db/models.py` is the
single source of truth for the schema; add a step to `STEPS` in
`backend/db/migrations/steps.py` and bump `SCHEMA_VERSION` for each change.
