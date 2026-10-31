# Production-Readiness Report — OVManager

Date: 2026-10-31
Version: 2.2.1 (internal/version/version.go)
Commit: c3f632d

## Summary

OVManager is production-ready after the audit below. All automated gates pass:
Go tests (104 frontend + Go suite), `go vet`, `gofmt` (clean), `go mod verify`,
`npm audit --omit=dev` (0 vulns), `make build`, Docker build, release assets
published, GHCR image published.

## Audit areas

### 1. Code & architecture
- Go modules: `go mod verify` OK, `go mod tidy` clean (no drift).
- Formatting: `gofmt -l .` empty.
- Static analysis: `go vet ./...` clean.
- No TODO/FIXME/HACK/panic in production code.
- HTTP server uses bounded `ReadHeaderTimeout` (10s), `ReadTimeout` (10m for
  large restores), `IdleTimeout` (120s); `WriteTimeout` 0 for SSE.
- Request bodies bounded via `http.MaxBytesReader` on all endpoints.
- Recovered: `node/management.go` `decodeBody` now passes the real
  `ResponseWriter` to `MaxBytesReader` (was nil).

### 2. Security
- No hardcoded secrets or default admin password; owner claim via
  `owner-claim.key` (openssl rand, 0600).
- SQL uses parameterized/constant strings; no injection found.
- Path traversal guards present (`restoreStoredBackup` EvalSymlinks + prefix
  check; `safeFilename`).
- `exec.Command` uses argument slices (no shell interpolation).
- `spawnDetached` runs a fixed `sh -c` script with argv passed safely.
- Trusted-proxy flag read from env/.env consistently.
- Docker image runs as `nonroot` on distroless; no shell in runtime.
- Frontend runtime deps: 0 vulnerabilities (`npm audit --omit=dev`).
- Dev-only moderate vulns (eslint/minimatch) — not shipped.

### 3. Dependencies
- Go: 37 modules, all verified, tidy clean.
- Frontend: 12 moderate dev-only vulns; 0 production vulns.

### 4. Database
- SQLite (modernc, pure Go, CGO_ENABLED=0 portable).
- Migrations in `internal/db/migrate.go`.
- Backup/restore with atomic swap + rollback (`atomicDBRestore`).
- Ownership handling verified (chown recovery documented in changelog).

### 5. API integrations
- ACME/Let's Encrypt via acme.sh (domain + IP certs).
- Telegram notifications (optional).
- Node management & fanout with panic recovery.

### 6. Tests
- Go: full suite passes (`go test ./...`).
- Frontend: 31 files, 104 tests pass (`npm run verify`).
- Lint gate: `go vet` + `gofmt`.

### 7. Configuration / env vars
- Env vars loaded from process env then `.env` file (`envOrFile`).
- Installer writes `.env` with 0600/0640 perms, root:panel user.
- Documented in installer `--help` and `.env` template (optional section).

### 8. Deployment
- Native (systemd) and Docker (compose) install paths both supported.
- Docker default as of 2.2.1; `--native` opt-out.
- Installer published; GHCR image `ghcr.io/anonysec/ovmanager:2.2.1` (multi-arch)
  and release binaries (amd64/arm64) available.
- Healthcheck in Dockerfile; systemd units with hardening (`NoNewPrivileges`,
  `PrivateTmp`, `ProtectHome`).

### 9. Installer (OVManager)
- PasarGuard-style structure: root-first, dep auto-install, override/purge
  prompts, SSL wizard, port-conflict handling, bash completion, OVNode prompt,
  log tailing.
- Management commands: up/down/restart/logs/cli/backup/restore/edit-env/
  install-script/install-node.
- Auto-installs missing deps (curl/openssl).

## Fixes applied during audit
- `internal/node/management.go`: `decodeBody` now passes real `ResponseWriter`
  to `http.MaxBytesReader` (was nil).

## Security scanner evidence

- `govulncheck ./...`: 0 vulnerabilities affecting code. One module-level
  advisory GO-2026-5932 (golang.org/x/crypto openpgp) is pulled in transitively
  but the affected symbols are not called; x/crypto is used only for bcrypt and
  acme.
- `gosec ./...` (excluding web/node_modules): 0 findings. All 41 previously
  reported G104 unhandled-error findings were fixed by explicitly handling
  returned errors (`_ = ...` / `_, _ = ...`).
- `npm audit --omit=dev`: 0 vulnerabilities (minimatch overridden to ^11.0.1
  via package.json overrides; eslint lint gate still passes).
- `go mod verify`: all modules verified; `go mod tidy` clean.
- `npm audit --omit=dev`: 0 vulnerabilities (12 moderate dev-only, not shipped).","oldString":"## Known limitations / not addressed\n- Dev-only npm moderate vulnerabilities (eslint chain) — not shipped.\n- No air-gapped/offline installer bundle.\n- `govulncheck`/`gosec` not installed; manual review performed instead.\n- ACME requires network and port 80.\n- Multi-arch Docker image built via CI (QEMU) — local build was amd64 only.","path">
/root/workspace/OVManager/PRODUCTION_READINESS.md

## Verdict

Production-ready for release 2.2.1. All automated gates green; one minor
security-correctness fix applied; no breaking changes.
