# OVManager

[![CI](https://github.com/anonysec/OVManager/actions/workflows/ci.yml/badge.svg)](https://github.com/anonysec/OVManager/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-blue)](CHANGELOG.md)

OpenVPN management panel. Works with [OVNode](https://github.com/anonysec/OVNode) for node-side VPN management.

| Panel | Node | Status |
| ----- | ---- | ------ |
| 1.2.x | 1.1.x | supported (sync API contract) |
| 2.x   | ≥ 2.0 | retired |

## Acceptable use

You operate the VPN: abuse complaints (spam, scanning, copyright) go to
**you**, not to this project. Enforce per-user traffic quotas and expiry,
watch Security → Authentication Summary, disable abusers promptly, and
respect your provider's ToS and local law.

## Quickstart (beginners start here)

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
```

Choose **Install** (recommended) or **Install with Docker**. OVManager uses port
`2095`, generates a private panel URL, and prints a one-time **claim key** — no
password is created at install time. Open the printed URL, paste the key, and
choose the owner password in the browser (lost the key? `ovm owner-claim`).
Then follow the built-in setup checklist (node → user → download `.ovpn`).

Step-by-step with pictures-in-words: [docs/quickstart.md](docs/quickstart.md) ·
under the hood: [docs/how-it-works.md](docs/how-it-works.md) ·
one server: [docs/single-vps.md](docs/single-vps.md) ·
many servers: [docs/multi-node.md](docs/multi-node.md) ·
stuck: [docs/troubleshooting.md](docs/troubleshooting.md).

## Install

The installer has two modes — **native** (systemd + uv on the host) and **Docker**
(image built from source). Humans get a wizard; scripts pass flags and never wait
on a prompt.

**Human** (keeps the terminal as stdin so the wizard can ask):

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
```

**Unattended** (`--yes` skips every prompt; the panel URL and the one-time claim
key are printed):

```bash
# Install
curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh \
  | sudo bash -s -- --yes

# Install with Docker
curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh \
  | sudo bash -s -- --docker --yes
```

The private URL path is always generated for a fresh recommended installation.
The owner password is never an install input — the install prints a claim key
and you set the password in the browser. `CI=true` implies `--yes`. Run the
script with `--help` for the three flags and the `OVM_*` equivalents.

Forks: `OVM_REPO=myorg/OVManager` points source downloads and update
pulls at your own repo (use your fork's raw `install.sh` URL to install
from it).

`-p/--pass`, `--mode`, `--tls*` and `-i` are deprecated (they still work, and
each prints what replaces it): every install setting is an `OVM_*` variable, so
an unattended run and an interactive one cannot disagree.

## Update / Uninstall

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) update
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) uninstall
# also drop data:
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) uninstall --purge
# owner password lives in the DB — set it with the CLI (-p for scripts, or OVM_PASS):
ovm reset-password
OVM_PASS='new-password' ovm reset-password
```

Stuck on ≤1.2.5 with a checksum error? Re-bootstrap with the one-liner
above, then `update` (`ovm update` alone still uses the old installer).

## Terminal menu

Every install adds a command — run `ovmanager` (or `ovm`) on the server and
pick from a menu: **Status · Start/Stop/Restart · Logs · Backup · Auto
backup · Update · TLS · Recovery · Uninstall**. Recovery shows the panel URL and login, resets
the owner password (rewrites the owner's database row), or clears the secret URL path. `logs -f` follows live;
with `whiptail` installed the menu uses boxed dialogs.

Every item is also a plain command for scripts (stable exit codes):
`ovmanager status | start | stop | restart | logs [N|-f] | backup | update |
tls | recovery | reset-password | reset-urlpath | menu | help`.

## Manual Install (developers only — beginners: use the installer above)

```bash
git clone https://github.com/anonysec/OVManager.git /opt/ovmanager
cd /opt/ovmanager
cp .env.example .env   # set PUBLIC_URL; the owner credential is created below
pip install uv && uv sync
cd frontend && npm ci && npm run build
uv run main.py
# first run creates the schema and the owner row; set its password with:
.venv/bin/python -m cli.main reset-password -p 'a-strong-password'
```

### Developer commands

`make` wraps the checks, so you do not have to remember the incantations or
run them one at a time:

| Target | What it runs |
| --- | --- |
| `make setup` | `uv sync --frozen` and `npm ci` — installs exactly what the lock files pin. |
| `make test` | The backend suite, `pytest -n auto`. Parallel is safe because each xdist worker imports `conftest`, which allocates its own throwaway data directory. |
| `make lint` | `ruff check` and `ruff format --check` over backend, bot, cli, tests and bench; `bash -n` on the shell entrypoints; `git diff --check`; and `eslint src/` in the frontend. |
| `make verify` | `lint`, then the frontend's `npm run verify` (build, design tokens, i18n key parity, RTL, eslint, types, vitest), then regenerates `scripts/openapi.json`. |
| `make bench` | The node fan-out benchmarks in `scripts/bench/`. Not a test — the figures depend on the machine's core count. |
| `make openapi` | Regenerate `scripts/openapi.json` from the app on its own. |
| `make clean` | Drop build artefacts and caches. |

`make verify` does **not** run the backend test suite — that is `make test`.
Run both before pushing; CI runs the same checks, in three parallel jobs
(`backend`, `frontend`, `frontend-dist`) rather than one target.

### Container image

The `Dockerfile` is three stages, and the split is the point — the runtime
image should carry nothing a running panel does not need:

1. **`frontend`** (`node:22-slim`) builds the SPA. Node never reaches the
   runtime stage.
2. **`builder`** (`python:3.12-slim`) installs `uv` and runs
   `uv sync --frozen --no-dev`, which fails closed if `pyproject.toml` and
   `uv.lock` have drifted apart. `gcc` is installed here and only here: it is
   needed to build wheels, and it never reaches the runtime image.
3. **`runtime`** (`python:3.12-slim`) ships the venv, the sources and the
   frontend build — no compiler, no `uv`, no build tooling.

It runs as a non-root `appuser` in the `ovpanel` group (gid 997), which is what
lets the container read the config bind-mounted at `/app/.env`. The installer
refuses a gid that already has members on the host, because sharing that file
by group would hand the secret panel URL path to them.

## Panel path (URLPATH)

The panel can be served under a secret URL prefix (e.g. `/k3f9xq2m/`) which
hides it from internet scanners: requests outside the prefix get an empty
404, so the server looks like an ordinary empty website.

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

The panel has no external broker and no shared-state service. The web server
runs with `workers=1` and keeps its state in-process; SQLite is the only
datastore. It supervises its own children — a jobs process (`worker.py`) and,
when the bot is enabled, the Telegram bot (`bot_supervisor.py`) — so a job that
blocks cannot stop the panel answering, and a crashing child is restarted
rather than taking the panel with it. The children are supervised, not peers:
the jobs child takes an exclusive lock on the data directory so a second one
cannot start and double every schedule. See
[docs/how-it-works.md](docs/how-it-works.md) for the full process model.

**Redis was evaluated and not added.** It is the right answer when several
application processes must share cache or pub/sub state. Here the web process
is the only reader of the live cache, and the children do not share it — they
coordinate through SQLite, which is already the source of truth — so a Redis
hop would only add latency, a second thing to run and back up, and roughly
10–30 MB of resident memory: the opposite of the goal. Introducing it only
becomes worthwhile if OVManager moves to multiple *web* workers, which would
also require replacing SQLite with a networked database first.

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

## Free for personal and commercial use

OVManager is licensed under the [MIT License](LICENSE). You may use, modify,
distribute, host, and sell services built with it without paying this project
a license fee. There is no license server, paid feature gate, node limit, or
user limit. Keep the copyright and MIT license notice with copies or substantial
portions of the software. Third-party infrastructure and components retain
their own terms.

See [Privacy](docs/legal/PRIVACY.md), [Acceptable use](docs/legal/ACCEPTABLE_USE.md), and
[third-party licensing](docs/legal/THIRD_PARTY_LICENSES.md).
