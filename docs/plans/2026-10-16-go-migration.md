# OVManager Go Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port OVManager backend (Python/FastAPI) to Go, merging `manager.sh` + `cli/` into one binary, keeping the TS frontend untouched.

**Architecture:** Strangler pattern. Go binary serves new endpoints alongside Python during migration; SQLite stays the shared contract (additive migrations only, SCHEMA_VERSION keeps climbing). Frontend switches API base per-module as ports land. Final cutover deletes Python backend.

**Tech Stack:** Go 1.24+, stdlib net/http (chi router), modernc.org/sqlite (pure-Go, no cgo), golang-jwt or PASETO for sessions, cobra for CLI commands, x/crypto for hashing/TLS.

**Spec:** docs/superpowers/specs/ — decisions: strangler not big-bang; frontend untouched; DB additive-only; one binary (panel+cli+manager); bash keeps curl-pipe stub + systemd/ACME glue only.

## Global Constraints

- SCHEMA_VERSION (currently 26) only moves forward; every Go migration adds to backend/db/migrations/steps.py parity (Go runner must apply the same steps).
- API shapes byte-identical (frontend depends on them; parity tests enforce).
- No new Python code except parity shims; each phase deletes the Python it replaces.
- Touch only files the task lists.
- Commit per phase: `feat(go): <phase slug>`.

## Review Focus

- Session/claim semantics diverge between implementations (owner key, session tokens) — parity test per auth path.
- Node mTLS pinning mistranslated (server_ca pin check) breaks all node comms silently.
- Migration runner ordering differs (Go vs Python step sort) corrupting SCHEMA_VERSION.
- SSE/telemetry stream framing changes break the frontend EventSource client.
- Timezone/rounding in billing ledger differs by cents (compare golden outputs).

---
### Phase 0: Skeleton + contract harness

**Files:**
- Create: `go.mod`, `cmd/ovmanager/main.go`, `internal/version/version.go`, `internal/health/health.go`, `internal/db/open.go`
- Test: `goparity/health_test.go` (httptest: GET /health → {"status":"ok","version":...})

**Interfaces:**
- Consumes: backend/version.py (__version__ = "1.6.0"), backend/app.py /health shape.
- Produces: module `ovmanager-go`, runnable binary serving /health with matching version, SQLite open helper.

- [ ] **Step 1: Write failing parity test**

```go
func TestHealthMatchesPython(t *testing.T) {
    // GET /health on Go server, compare status+version keys to backend/app.py contract
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./goparity/ -run TestHealthMatchesPython -v`
Expected: FAIL (no server yet)

- [ ] **Step 3: Implement skeleton (main.go, version, health handler, db open with modernc.org/sqlite)**
- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./goparity/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add go.mod cmd/ internal/ goparity/
git commit -m "feat(go): skeleton and health parity"
```

---
### Phase 1: Auth + users (highest risk first)

**Files:**
- Create: `internal/auth/{handler,session,claim,hash}.go`, `internal/users/handler.go`
- Modify: `backend/routers/users.py` (delete at phase end), `backend/auth/*` (delete at phase end)
- Test: `goparity/auth_test.go`, `goparity/users_test.go` (golden: login, claim, CRUD, 401/403/404/409 shapes incl. our recent 4xx changes)

**Interfaces:**
- Consumes: Phase 0 db helper; backend/auth/{auth,authz,sessions,hash}.py semantics.
- Produces: working /login /claim /users/* on Go binary.

- [ ] **Step 1: Write failing parity tests (auth flows + users CRUD incl. 409 duplicate, 404, 410 expired)**
- [ ] **Step 2: Run to verify they fail**

Run: `go test ./goparity/ -run 'TestAuth|TestUsers' -v`
Expected: FAIL

- [ ] **Step 3: Implement auth (x/crypto hashing must verify existing Python hashes; session token format identical; owner-claim.key flow identical)**
- [ ] **Step 4: Implement users CRUD with exact status codes (200 envelope vs 4xx per current behavior)**
- [ ] **Step 5: Run parity tests**

Run: `go test ./goparity/ -v`
Expected: PASS

- [ ] **Step 6: Delete ported Python (routers/users.py, auth/*) and commit**

```bash
git add -A && git commit -m "feat(go): auth and users port"
```

---
### Phase 2: Nodes (mTLS core)

**Files:**
- Create: `internal/node/{client,sync,fanout,pki,management}.go`
- Modify: delete `backend/node/*`, `backend/routers/node.py` at phase end
- Test: `goparity/node_test.go` (pin verification against test fixtures, sync shapes, fanout behavior; NODE_TLS_INSECURE_FALLBACK default fail-closed preserved)

**Interfaces:**
- Consumes: Phase 0–1 (db, auth middleware).
- Produces: /nodes/* on Go; node sync worker in Go.

- [ ] **Step 1: Write failing parity tests (pin check accept/reject, status shapes, unreachable semantics)**
- [ ] **Step 2: Run to verify they fail**

Run: `go test ./goparity/ -run TestNode -v`
Expected: FAIL

- [ ] **Step 3: Implement node client (crypto/tls with server_ca pin, verify=False fallback only behind flag)**
- [ ] **Step 4: Implement sync + fanout workers (same intervals, same payload shapes)**
- [ ] **Step 5: Run parity tests**

Run: `go test ./goparity/ -v`
Expected: PASS

- [ ] **Step 6: Delete ported Python and commit**

```bash
git add -A && git commit -m "feat(go): node core port"
```

---
### Phase 3: Telemetry/SSE + billing ledger (golden outputs)

**Files:**
- Create: `internal/telemetry/{handler,stream}.go`, `internal/billing/ledger.go`
- Modify: delete `backend/routers/telemetry.py`, `backend/operations/observability/*`, `backend/operations/billing/*` at phase end
- Test: `goparity/telemetry_test.go`, `goparity/billing_test.go` (SSE framing byte-compare; ledger golden file: run Python ledger on fixture DB, compare Go output cent-for-cent)

**Interfaces:**
- Consumes: Phase 0–2.
- Produces: /notifications /activity /metrics /live + SSE; billing ledger identical.

- [ ] **Step 1: Write failing tests (SSE frame capture vs Python output; ledger golden from tests/fixtures)**
- [ ] **Step 2: Run to verify they fail**

Run: `go test ./goparity/ -run 'TestTelemetry|TestBilling' -v`
Expected: FAIL

- [ ] **Step 3: Implement handlers (sync DB reads — no event-loop issue in Go; keep batching from prior fix)**
- [ ] **Step 4: Implement SSE stream (same event names, same retry field, same JSON shapes)**
- [ ] **Step 5: Implement ledger (decimal math — use shopspring/decimal, golden-compare)**
- [ ] **Step 6: Run parity tests**

Run: `go test ./goparity/ -v`
Expected: PASS

- [ ] **Step 7: Delete ported Python and commit**

```bash
git add -A && git commit -m "feat(go): telemetry and billing port"
```

---
### Phase 4: Remaining routers (setting, security, tls, updater, maintenance, sub, owner_claim)

**Files:**
- Create: `internal/panel/*.go` (one package, one file per router area)
- Modify: delete remaining `backend/routers/*`, `backend/operations/*` leftovers at phase end
- Test: `goparity/panel_test.go` (per-endpoint status/shape table, TLS cert validation behavior incl. traversal rejection, updater state machine shapes)

**Interfaces:**
- Consumes: Phase 0–3.
- Produces: full API surface on Go; Python backend fully deleted.

- [ ] **Step 1: Write failing endpoint table test (route list from Phase inventory, ~85 endpoints)**
- [ ] **Step 2: Run to verify it fails**

Run: `go test ./goparity/ -run TestPanelSurface -v`
Expected: FAIL

- [ ] **Step 3: Implement remaining handlers (TLS upload/validation, updater endpoints, settings CRUD, sub page, maintenance)**
- [ ] **Step 4: Run table test**

Run: `go test ./goparity/ -v`
Expected: PASS

- [ ] **Step 5: Delete backend/ entirely (keep backend/ dir only if frontend imports it — it doesn't) and commit**

```bash
git add -A && git commit -m "feat(go): full api surface, python backend removed"
```

---
### Phase 5: CLI + manager merge (one binary)

**Files:**
- Create: `cmd/ovmanager` subcommands via cobra: status, logs, doctor(-fix), backup, restore, tls, urlpath, reset-password, update (orchestrates release fetch + verify + failover, ported from install.sh do_update logic), service stubs
- Modify: delete `cli/*`, `manager.sh` at phase end (keep curl-pipe stub + minimal systemd/ACME glue in slimmed install.sh)
- Test: `goparity/cli_test.go` (golden CLI output for status/doctor against fixture DATA_DIR; update dry-run path)

**Interfaces:**
- Consumes: Phase 0–4 (all internal packages).
- Produces: single `ovmanager` binary = panel + ovm commands.

- [ ] **Step 1: Write failing CLI golden tests**
- [ ] **Step 2: Run to verify they fail**

Run: `go test ./goparity/ -run TestCLI -v`
Expected: FAIL

- [ ] **Step 3: Implement cobra commands (port cli/*.py + manager.sh delegates, root-gate host commands)**
- [ ] **Step 4: Port update orchestration (backup → stage → verify → failover; fix the dev-layout verify gap found in v1.6.0)**
- [ ] **Step 5: Run CLI tests**

Run: `go test ./goparity/ -v`
Expected: PASS

- [ ] **Step 6: Delete cli/ + manager.sh, slim install.sh to bootstrap, commit**

```bash
git add -A && git commit -m "feat(go): cli and manager merged, one binary"
```

---
### Phase 6: Cutover + harden

**Files:** none new (packaging only)

- [ ] **Step 1: Full Go test suite**

Run: `go test ./...`
Expected: PASS

- [ ] **Step 2: Frontend verify against Go panel (boot Go binary with fixture DATA_DIR, run `npm run verify`-adjacent smoke: /health + login + one page API)**

Run: `npm run verify` (from frontend/, against Go-served API if configurable; else note)
Expected: PASS or documented gap

- [ ] **Step 3: Fresh-install test on throwaway dest (`./install.sh --from-source` with Go tree → /tmp/ovm-go-test, boot, /health)**

Run per Phase-5 install path
Expected: `{"status":"ok","version":...}`

- [ ] **Step 4: Release v2.0.0 (version bump everywhere per parity rule, push, publish Release, verify live update works — including the fixed dev-layout verify)**

Run: `ovm update` on host after release assets land
Expected: live reports new version, no failover
