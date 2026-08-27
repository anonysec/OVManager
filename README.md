# OVManager

OpenVPN management panel. Works with [OVNode](https://github.com/anonysec/OVNode) for node-side VPN management.

## Install

The installer has two modes — **native** (systemd + uv on the host) and **Docker**
(image built from source). Humans get a wizard; scripts and AI pass flags and
never wait on a prompt.

**Human** (keeps the terminal as stdin so the wizard can ask):

```bash
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh)
```

**AI / CI / scripts** (`-y` skips every prompt; `--json` prints the result on stdout):

```bash
# Native
curl -sSL https://anonysec.github.io/OVManager/install.sh \
  | sudo bash -s -- -y --mode native --admin-pass 'choose-a-long-password'

# Docker
curl -sSL https://anonysec.github.io/OVManager/install.sh \
  | sudo bash -s -- -y --mode docker --admin-pass 'choose-a-long-password' --json
```

Useful flags: `--port 2095` `--path dash` (or `--path root` for `/`) `--tls-self`
`--tls-le example.com` `--dry-run`. Same values can be set with `OVM_MODE`,
`OVM_PORT`, `OVM_PATH`, `OVM_ADMIN_USER`, `OVM_ADMIN_PASS`, `OVM_TLS`.
`CI=true` implies `--yes`. Run the script with `--help` for the full list.

If `--admin-pass` is omitted under `-y`, a password is generated and printed
(and included in `--json`).

## Update / Uninstall

```bash
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh) update
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh) uninstall
# also drop data:
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh) uninstall --purge
```

## Manual Install

```bash
git clone https://github.com/anonysec/OVManager.git /opt/ovmanager
cd /opt/ovmanager
cp .env.example .env  # edit with your settings
pip install uv && uv sync
cd frontend && npm ci && npm run build
uv run main.py
```

## Panel path (URLPATH)

The panel can be served under a secret URL prefix (e.g. `/k3f9xq2m/`) which
hides it from internet scanners: requests outside the prefix get an empty
response, not even a 404.

- The installer generates a **random path by default** (override with
  `--path mypath`, or `--path root` to serve at `/`).
- Change it anytime in **Settings → General → Panel URL Path** — takes
  effect immediately, no restart. Prefixes of real routes (`api`, `assets`,
  `health`, subscription path, …) are rejected automatically.
- The prefix is scanner-hiding, **not authentication** — admin login + rate
  limiting protect the panel either way. Subscription links (`/sub/...`)
  and `/health` are intentionally served without the prefix: links must be
  shareable with users and healthchecks must keep working.

Forgot the path? Recover with shell access:

```bash
cd /opt/ovmanager && uv run main.py --reset-urlpath   # panel goes back to /
```

## Schema migrations

The database is migrated automatically on every start. The current version is
recorded in a `schema_version` table, so numbered steps run once and in order:

```bash
uv run python -m backend.db.migrations --check    # CI drift gate
uv run python -m backend.db.migrations --migrate  # apply to the live database
```

Databases created by an earlier release are **adopted**: their current shape is
inspected, missing columns are added, and the database is then stamped at the
current version. No dump/restore is needed. `backend/db/models.py` is the single
source of truth for the schema; add a step to `STEPS` in
`backend/db/migrations.py` and bump `SCHEMA_VERSION` for each change.

## Performance notes

The panel is deliberately a single process with no external broker. Uvicorn
runs with `workers=1`, state is in-process, and SQLite is the only datastore —
so there is nothing to coordinate between processes and no extra service to
run, secure, or keep alive.

**Redis was evaluated and not added.** It is the right answer when several
application processes must share cache or pub/sub state. Here there is exactly
one process, so a Redis hop would only add latency, a second thing to run and
back up, and roughly 10–30 MB of resident memory — the opposite of the goal.
Introducing it only becomes worthwhile if OVManager moves to multiple workers,
which would also require replacing SQLite with a networked database first.

What is done instead:

- One background collector polls the nodes and caches the result; request
  handlers read that cache instead of fanning out to every node per request.
- The collector backs off to `OVMANAGER_LIVE_IDLE_POLL_SECONDS` (default 300s)
  when no browser has the live stream open, instead of probing every node every
  10 seconds for an audience of nobody.
- Security-header and CSRF handling are plain ASGI middlewares, so requests do
  not pay for Starlette's `BaseHTTPMiddleware` task-and-queue wrapper — which
  also keeps the SSE stream unbuffered.
- The built `index.html` is cached in memory and invalidated by mtime, so
  serving an SPA route is one `stat()` rather than a file read per navigation.

## License

Proprietary. See [LICENSE](LICENSE).
