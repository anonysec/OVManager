# Go Migration Phase 6 — Cutover Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Finish the Go cutover: wire the full panel router into the binary, port the one missing legacy TLS helper, delete Python remnants (`main.py`, `cli/`, `manager.sh`, `pyproject.toml`, `scripts/`, `tests/`, `Dockerfile`), slim `install.sh` to a bootstrap that installs the Go binary, and ship v2.0.0 so live `ovm update` succeeds (fixing the dev-layout verify gap from v1.6.0).

**Architecture:** Single Go binary = panel + `ovm`. `main.go` runs the panel when invoked bare, routes subcommands to cobra. `install.sh` becomes: fetch release tarball (Go binary + frontend/dist), extract to `$INSTALL_DIR`, write systemd unit, restart, verify `/health` returns the release version. `manager.sh` deleted; `ovm` is the binary itself (symlinked to `/usr/local/bin/ovm`).

**Tech Stack:** Go 1.27, cobra, chi (already in `internal/panel`), modernc.org/sqlite. No Python anywhere in the runtime.

**Spec:** docs/superpowers/plans/2026-10-16-go-migration.md (Phases 5–6). This plan fills the gaps the prior lane flagged.

## Global Constraints

- `SCHEMA_VERSION` parity preserved (still 26; Go migration runner now must apply steps — Phase 6.2).
- API shapes unchanged (frontend depends on them).
- No new deps beyond what `go.mod` already has.
- Touch only files listed in each task.
- Commit per task.

## Review Focus

- Wiring the panel router into `main.go` without breaking the bare-vs-subcommand split.
- `migrate_legacy_tls` semantics must match the deleted Python (read the last Git version from the commit that deleted it).
- `install.sh` rewrite must not lose the dev-layout verify fix.
- `tests/` deletion removes the pytest suite — confirm no other CI references it.
- `pyproject.toml` deletion breaks `release.yml` (reads version from it) — must point at `internal/version/version.go` or `go.mod`.

---
### Task 1: Wire full panel router into main.go

**Files:**
- Modify: `cmd/ovmanager/main.go`
- Test: `goparity/main_test.go` (binary serves /health AND /api/health AND /login 405/401 shapes)

**Interfaces:**
- Consumes: `internal/panel.Handler()`, `internal/auth.RequireUser`, `internal/health.Router()`.
- Produces: single binary that is both panel and CLI.

- [ ] **Step 1: Write failing test** (`goparity/main_test.go`: build binary, exec it, assert /health + /api/users requires auth)
- [ ] **Step 2: Run to verify it fails**

Run: `go test ./goparity/ -run TestBinaryServesPanel -v`
Expected: FAIL

- [ ] **Step 3: Modify main.go** — when no subcommand, call `panel.Handler()` (mount health + all routers + static frontend/dist) and `http.ListenAndServe`
- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./goparity/ -run TestBinaryServesPanel -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cmd/ovmanager/main.go goparity/main_test.go
git commit -m "feat(go): wire full panel router into binary"
```

---
### Task 2: Port migrate_legacy_tls

**Files:**
- Create: `internal/panel/tls_legacy.go`
- Test: `goparity/tls_legacy_test.go`

**Interfaces:**
- Consumes: `internal/tls_config` (if exists), `internal/panel` settings row.
- Produces: `MigrateLegacyTLS(dataDir)` that mirrors the deleted Python helper.

- [ ] **Step 1: Recover deleted implementation**

Run: `git show 07204ee^:backend/...` (find the file that defined it) — inspect, then port
- [ ] **Step 2: Write failing test** (legacy cert files present → migrated; idempotent on second call)
- [ ] **Step 3: Run to verify it fails**
- [ ] **Step 4: Implement**
- [ ] **Step 5: Run test to verify it passes**
- [ ] **Step 6: Commit**

```bash
git add internal/panel/tls_legacy.go goparity/tls_legacy_test.go
git commit -m "feat(go): migrate_legacy_tls ported"
```

---
### Task 3: Migration runner parity

**Files:**
- Create: `internal/db/migrate.go`
- Test: `goparity/migrate_test.go`

**Interfaces:**
- Consumes: `backend/db/migrations/steps.py` (read last Git version from `07204ee^`) + `internal/db/open.go`.
- Produces: `Migrate(db)` applying steps 1..SCHEMA_VERSION idempotently; version tracked via PRAGMA user_version.

- [ ] **Step 1: Read deleted steps.py from Git, list steps 1..26 with their SQL**
- [ ] **Step 2: Write failing test** (fresh DB → user_version=26; re-run idempotent)
- [ ] **Step 3: Run to verify it fails**
- [ ] **Step 4: Implement** (one function per step, in order)
- [ ] **Step 5: Run test to verify it passes**
- [ ] **Step 6: Commit**

```bash
git add internal/db/migrate.go goparity/migrate_test.go
git commit -m "feat(go): migration runner parity with python steps 1-26"
```

---
### Task 4: Delete Python remnants

**Files:**
- Delete: `main.py`, `cli/`, `manager.sh`, `pyproject.toml`, `scripts/`, `tests/`, `Dockerfile`, `backend/` (already gone), `uv.lock`
- Modify: `.github/workflows/ci.yml`, `release.yml`, `docker.yml` (point at Go build; version from `internal/version/version.go`)
- Modify: `Makefile` (Go build targets; keep `npm` frontend targets)

**Interfaces:**
- Consumes: Tasks 1–3 (Go binary must be self-sufficient before deletion).
- Produces: repo with no Python runtime.

- [ ] **Step 1: Audit CI references**

Run: `grep -rn "pytest\|pyproject\|uv sync\|main.py" .github/ Makefile 2>/dev/null`
Expected: list of references to update

- [ ] **Step 2: Delete remnants**

```bash
git rm main.py pyproject.toml uv.lock Dockerfile
git rm -r cli/ scripts/ tests/
git rm manager.sh
```

- [ ] **Step 3: Update CI workflows** (build Go binary, run `go test ./...`, frontend verify; version extraction from `internal/version/version.go`)
- [ ] **Step 4: Update Makefile** (`make build` → `go build`, `make test` → `go test ./...`, keep `make verify` frontend)
- [ ] **Step 5: Run full verify**

Run: `go test ./... && (cd frontend && npm run verify)`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(go): python remnants removed, ci on go"
```

---
### Task 5: Slim install.sh to bootstrap

**Files:**
- Rewrite: `install.sh` (bootstrap-only: fetch Go release tarball, extract, write systemd unit, restart, verify)
- Delete: `install-local.sh` (already gone)
- Test: `tests/test_install_from_source.py` → rewrite as `tests/test_install_go.py` (Go-specific)

**Interfaces:**
- Consumes: Task 4 (release tarball now contains Go binary + frontend/dist).
- Produces: installer that works for dev (`--from-source`) and release (default).

- [ ] **Step 1: Write bootstrap install.sh** — fetch release, extract Go binary + frontend/dist, write unit, restart, `/health` verify with version match (fixing v1.6.0 dev-layout gap)
- [ ] **Step 2: Run bash -n + dry-run against /tmp**
- [ ] **Step 3: Rewrite install tests**
- [ ] **Step 4: Run tests**

Run: `pytest tests/test_install_go.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_install_go.py
git commit -m "feat(installer): bootstrap go binary, drop python venv"
```

---
### Task 6: Cutover + release v2.0.0

**Files:** none new (release only)

- [ ] **Step 1: Bump version**

Modify: `internal/version/version.go` → "2.0.0"; update `pyproject.toml` gone, so only Go file + CHANGELOG heading

- [ ] **Step 2: Full verify**

Run: `go test ./... && (cd frontend && npm run verify)`
Expected: PASS

- [ ] **Step 3: Commit + push**

```bash
git add -A && git commit -m "chore(release): v2.0.0" && git push origin HEAD
```

- [ ] **Step 4: Publish release**

Run: `gh release create v2.0.0 --title "v2.0.0" --generate-notes` (assets workflow builds tarball)
Expected: release URL

- [ ] **Step 5: Live update test**

Run: `ovm update` (now the Go binary's update command)
Expected: live reports 2.0.0, no failover, no dev-layout verify gap

- [ ] **Step 6: Report completion** to user with: version live, tests green, Python removed, binary size, RAM observed.
