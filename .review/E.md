# OVManager Release Engineering Review — E.md

Read-only review: README.md, SECURITY.md, CHANGELOG.md, LICENSE/NOTICE, install.sh, Dockerfile, Makefile, cmd/ + internal/cli/ + internal/db, test/. No tracked files modified.

## 1) GOVERNANCE TRUTH — CHANGELOG vs git history

- `package.json:4` says `"version": "2.1.2"` — matches `internal/version/version.go:11` `Version = "2.1.2"` ✓
- `install.sh:37` hardcodes `VERSION="2.1.2"` with comment at line 36 saying it must match `internal/version/version.go` ✓
- `go.mod:3` says `go 1.26.0` but README line 12 badge says `go-1.27+` and `install.sh:341` says "install Go 1.27+" — **VERSION MISMATCH** (1.26 vs 1.27)
- CHANGELOG top entries:
  - `2.1.2 — 2026-10-18` (line 1): only "Fix: fresh installs created an empty database (db.Migrate was never called in main.go)"
  - `2.1.1 — 2026-10-18` (line 5): SPA 404 fix, DATA_DIR fix, from-source update check
- `git log --oneline -30`: `chore(release): bump to 2.1.2` at commit `27ebbee`, date `2026-10-18 21:53:12 +0000`
- **ALL traffic accounting / live snapshot / race fix commits merged AFTER the 2.1.2 bump**, on `2026-10-19` (02–03 UTC), NOT in any CHANGELOG entry:
  - `d74bdc1` Merge usage accounting + live snapshot wiring (2026-10-19 03:44)
  - `9aaa6cf` feat(users): populate active_connections from live snapshot
  - `c847b07` feat(users): wire top-traffic and per-day series to billing helpers
  - `0db5dbc` feat(panel): add traffic worker and sync-traffic route
  - `5dba760` fix(users): reset uses reseed marker instead of wiping baselines
  - `fb7db43` fix(users): skip reserved keys and resolve node ids in usage aggregation
  - `59f0b7e` feat(telemetry): parallelize CollectLiveSnapshot and fix CN mapping
  - `315d439` feat(node): implement SyncTraffic with OCC retry, seeding, and fanout
  - `58eec9f` fix(telemetry,panel): guard nodeState/checkState maps with mutex **(RACE FIX)**
  - `77dce10` fix(node): stop mutating shared Client.headers across goroutines **(RACE FIX)**
  - `a743795` chore: enforce gofmt in lint and make tablesReady sync.Once
- CHANGELOG dates match commit dates for 2.1.2 / 2.1.1 (both 2026-10-18) ✓, but features merged 2026-10-19 have **zero CHANGELOG coverage** — latest release does not include recently merged work.

## 2) DOCS ACCURACY

Env vars read in Go (28 matches across internal/ + cmd/) — documentation status:

Documented in `.env.example`:
- `ADMIN_USERNAME` — migrate.go:488,723,737 → .env.example:11 ✓
- `ADMIN_PASSWORD_HASH` — migrate.go:492 → .env.example:20-23 ✓
- `BOT_ENCRYPT_KEY` — migrate.go:795 → .env.example:56-59 (RETIRED) ✓
- `NODE_ENCRYPT_KEY` — migrate.go:808 → .env.example:56-59 (RETIRED) ✓
- `URLPATH` — migrate.go:414 → .env.example:38 ✓
- `PORT` — panel.go:244 → .env.example:33 ✓
- `HOST` — panel.go:237 → .env.example:32 ✓
- `SSL_KEYFILE`/`SSL_CERTFILE` — panel.go:211-221 → .env.example:48-49 ✓
- `SUBSCRIPTION_PATH` — panel.go:230 → .env.example:63 ✓
- `OVMANAGER_LIVE_POLL_SECONDS` — telemetry/handler.go:473 → .env.example:68 ✓
- `OVMANAGER_LIVE_IDLE_POLL_SECONDS` — telemetry/handler.go:465 → .env.example:71 ✓

Documented in `.env.example` but **NOT read in Go** (dead docs):
- `TRUSTED_PROXY` — .env.example:79-94, no Go consumer
- `SUBSCRIPTION_URL_PREFIX` — .env.example:62, no Go consumer
- `DEBUG`/`DOC` — .env.example:52-53, no Go consumer

**NOT documented anywhere** (.env.example / README / SECURITY):
- `OVM_APP_DIR` — cli/env.go:69, panel.go:147, updater.go:51, cmd/main.go:86
- `DATA_DIR` — panel.go:158, cli/env.go:78, cli/update.go:53, node/pki.go:19 (path /var/lib/ovmanager mentioned in README but not as env var)
- `NODE_TLS_INSECURE_FALLBACK` — client.go:146
- `OVM_REPO` — cli/update.go:124, panel/updater.go:66 (install.sh:28 mentions it)
- `OVM_PANEL_USER` — cli/doctor.go:30
- `OVM_ADMIN_PASS` — cli/password.go:16
- `OVM_ACME_DOMAIN` — panel/tls_acme.go:69 (install.sh/README mention it but .env.example does not)
- `OVM_ACME_DIRECTORY_URL` — panel/tls_acme.go:52
- `OVM_ACME_HTTP_PORT` — panel/tls_acme.go:58
- `LC_ALL`/`LC_CTYPE`/`LANG` — cli/render.go:18

CLI flags (cobra root, internal/cli/root.go) vs README quickstart:
- Global flags: `--install-dir` (root.go:48), `--data-dir` (49), `--in-container` (50), `--service-state` (51), `--public-ip` (52), `--all`/`-a` (53)
- Subcommands: status, logs, doctor, backup, restore, tls, urlpath, reset-password, update, service (root.go:57)
- README day-to-day table (lines 184-196) matches CLI surface but omits global flags like `--install-dir`, `--data-dir`, `--in-container`, `--public-ip`

README claims vs actual code:
- "SQLite only" (line 50) — matches `modernc.org/sqlite` in go.mod:9, no Postgres path ✓
- **Port mismatch**: line 77 says "`2083` is the only port the panel needs" but actual port is `2095` everywhere (line 108, Dockerfile:36 `EXPOSE 2095`, install.sh:32 `DEFAULT_PORT=2095`)
- "One background collector" live view (line 51) — matches `startLiveWorker()` panel.go:122 ✓

## 3) INSTALL / RELEASE

install.sh:
- Pins base checksums: YES — fetches `.sha256` sidecar, verifies with `sha256sum -c` (lines 94-99)
- Verifies sha256 of binary: YES (line 98-99)
- Refuses root-only: NO — **REQUIRES root** (`check_root` line 55: "Must run as root (sudo).")
- `--prefix` handling: **NO** — no such flag exists
- arm64 support: YES — `detect_arch` handles aarch64/arm64 (lines 73-74); release.yml builds both amd64 + arm64 (lines 60-64)
- Shellcheck: variables mostly quoted ✓
- `VERSION` hardcoded "2.1.2" at line 37 (guarded copy per line 36 comment)

Dockerfile:
- Base image `golang:1.27 AS build` (line 15) — **NOT pinned by digest**
- Runtime `gcr.io/distroless/static-debian12:nonroot` (line 28) — **NOT pinned by digest**
- Non-root `USER nonroot` (line 37) ✓
- **HEALTHCHECK: NO** — missing
- `EXPOSE 2095` (line 36) ✓
- Layer order: go.mod/go.sum first (good), then cmd/, internal/, web/dist/
- No secret baked in: clean

Makefile:
- Targets: setup, build, test, lint, verify, clean, version only
- **`make release` and `make image` do NOT exist** — release only via GitHub Actions release.yml
- `release.yml`: builds amd64+arm64, generates `.sha256` sidecars (lines 60-64), uploads to GitHub Release
- `docker.yml`: multi-arch, GHCR, trivy scan `continue-on-error: true` (line 69)
- `ci.yml`: coverage gate 44% (line 92), govulncheck

## 4) MIGRATIONS (internal/db/migrate.go)

- `SchemaVersion = 26` (line 28)
- Steps 2-26 (no step 1), versioned via `PRAGMA user_version` (line 146-158)
- **No DOWN statements** — all up-only
- **No transactions per migration** — each step runs individually and is stamped after (lines 112-123)
- Ordering matches names sequential 2-26 ✓
- `ALTER TABLE users DROP COLUMN owner` in step 24 `singleAdminSchema` (lines 751-758) — drops column, does not mutate BIGINT NULL-ability
- `migrate_test.go` expected list (lines 76-102) matches `migrate.go` steps (lines 524-659) exactly — versions 2-26, all descriptions identical
- No new migration added without test update — they match perfectly
- No migration versioned after v2.1.2 release — all 26 steps exist

## 5) TEST COVERAGE SKEW

`test/` has 23 `_test.go` files. Route → test coverage (routes registered in panel.go Mount, lines 51-125):

| Route | Test file(s) | Covered? |
|-------|-------------|----------|
| GET /health/overview | panel_test.go:221 | ✓ |
| GET /health/login-health | panel_test.go:223 | ✓ |
| GET /health/login-diagnostics/{username} | panel_test.go:225 | ✓ |
| GET /health/setup | panel_test.go:227 | ✓ |
| GET /health/tls | panel_test.go:229 | ✓ |
| GET /server/settings | panel_test.go:233 | ✓ |
| PUT /server/settings/timezone | panel_test.go:238 | ✓ |
| PUT /server/settings/subscription | panel_test.go:243 | ✓ |
| PUT /server/settings/domain | panel_test.go:253 | ✓ |
| PUT /server/settings/bot | panel_test.go:259 | ✓ |
| PUT /server/settings/urlpath | panel_test.go:273 | ✓ |
| POST /server/alerts/test | panel_test.go:268 | ✓ |
| GET /server/info | panel_test.go:280 | ✓ |
| GET /security/summary | panel_test.go:285 | ✓ |
| GET /maintenance/backup/list | panel_test.go:290 | ✓ |
| GET /maintenance/backup/download | panel_test.go:291 | ✓ |
| POST /maintenance/backup | panel_test.go:215 | ✓ |
| POST /maintenance/sync-limits | panel_test.go:293 | ✓ |
| POST /maintenance/clean-stale | panel_test.go:295 | ✓ |
| POST /maintenance/restart | panel_test.go:297 | ✓ |
| POST /maintenance/cleanup/preview | panel_test.go:299 | ✓ |
| POST /maintenance/cleanup/run | panel_test.go:302 | ✓ |
| POST /maintenance/usage/reset-all | panel_test.go:304 | ✓ |
| POST /maintenance/usage/purge | panel_test.go:309 | ✓ |
| GET /tls/settings | panel_test.go:316 | ✓ |
| PUT /tls/settings | panel_test.go:318 | ✓ |
| GET /tls/status | panel_test.go:328 | ✓ |
| GET /updater/status, /updater/operation, POST /updater/run | panel_test.go:585 | ✓ |
| GET /api/db/backup, POST /api/db/restore | dbops_test.go:107,195 | ✓ |
| POST /api/maintenance/backup | dbops_test.go:118 | ✓ |
| POST /api/maintenance/backup/restore | dbops_test.go | ✓ |
| POST /api/login, /api/logout, /api/refresh | auth_test.go | ✓ |
| GET/POST /api/owner-claim*, POST /api/owner-claim/verify | auth_test.go | ✓ |
| GET/POST/PUT/DELETE /api/users/* | users_test.go | ✓ |
| GET /api/activity/, /api/notifications/, /api/live/stream | telemetry_test.go | ✓ |
| GET /health | health_test.go | ✓ |

UNSORTED / uncovered routes:
- POST /tls/upload, /tls/self-signed, /tls/renew, /tls/rollback, /tls/restart, /tls/acme (panel.go:90-96) — panel_test.go truncated at line 328; coverage unclear
- POST /https/* aliases (panel.go:99-104) — coverage unclear
- GET /sub/static/subscription.js, /sub/download/{uuid}/{node_name}, /sub/{uuid} (panel.go:138-140) — **NOT covered by Go unit tests or e2e**

E2E (web/e2e): smoke.spec.ts, full.spec.ts, tls.spec.ts = 13 tests (matches "13 passing" in git log). Tests UI page loads (login, dashboard, users, nodes, logs, settings), health endpoint, security headers, assets — but does **NOT** map to backend route names and does **NOT** test subscription endpoints (/sub/*) or any API mutation routes.

## 6) RELEASE BLOCKER TRIAGE

- Hard-coded version strings: install.sh VERSION="2.1.2" (line 37) matches version.go:11 — OK but fragile dual source
- Missing CHANGELOG entry: traffic accounting / live snapshot / race fixes merged 2026-10-19 are NOT in CHANGELOG (2.1.2 bumped 2026-10-18 21:53, before those commits)
- Docs drift causing operator confusion: README line 77 says port 2083, actual port 2095 everywhere (Dockerfile:36, install.sh:32, README:108)
- Dockerfile CVE-exposed base: golang:1.27 (line 15) and gcr.io/distroless/static-debian12:nonroot (line 28) NOT pinned by digest
- `make release`: DOES NOT EXIST — no release/image targets in Makefile; release only via GitHub Actions release.yml
- No HEALTHCHECK in Dockerfile
- install.sh fetched via curl|bash — the installer script itself is not checksummed before execution (only the binary it downloads is)

## Top 3 if I only had 10 minutes — ranked by release risk

1. Missing CHANGELOG entry for post-2.1.2 merged work (traffic accounting, live snapshot, race fixes) — operators cannot verify what a release contains; the changelog is the release contract and it is silently incomplete.
2. Port mismatch README line 77 (2083) vs actual 2095 (Dockerfile:36, install.sh:32, README:108) — operator confusion, failed installs, firewall misconfiguration.
3. Dockerfile base images unpinned by digest (lines 15, 28) + no HEALTHCHECK — CVE exposure via stale base layers, no container health signal for orchestrators.
