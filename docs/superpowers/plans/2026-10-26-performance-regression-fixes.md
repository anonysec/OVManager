# Performance Regression Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Undo the panel-side work amplification the 2.1.2 working tree introduced (metrics collection every ~20 s instead of every 30 min, an 811 KB JSON refetch per live tick) and stop two silent operational regressions (TLS fallback, embedded-asset buildup).

**Architecture:** No new layers. Task 1 puts the metrics collector back behind one gate with a stated cadence, so the two background workers stop each running a full collect. Task 2 gives that collect the same bounded parallel fan-out every other node RPC site already uses. Tasks 3–4 cut the write and read amplification that followed from the higher cadence. Tasks 5–7 are one-line operational repairs.

**Tech Stack:** Go 1.27 (stdlib `net/http`, SQLite via `modernc.org/sqlite`), React 19 + Vite, Vitest + Testing Library, Make.

**Spec:** The audit that produced these tasks is the findings list in "Findings and evidence" below — each task cites its finding number. Load assumed: 1 node, 4 users, one operator browser today; correctness target ~20–50 nodes.

**Repo:** `/root/workspace/OVManager`. The working tree already carries ~143 files of uncommitted 2.1.2 work. Every `git add` below names its files explicitly — never `git add -A`.

## Global Constraints

- No new Go or npm dependencies. stdlib and what `go.mod` / `web/package.json` already carry.
- SQL is parameterised; never concatenate a value into a statement. DB access from a handler goes through `h.Svc.DB()`.
- Test seams are package-level vars reassigned by the suite (see `liveCollect` in `internal/panel/live_worker.go`). No DI container.
- `go test ./...`, `go vet ./...` and `gofmt -l .` (must be empty) are the Go gates. `cd web && npm run verify` is the frontend gate. Never lower `COVERAGE_MIN` (44).
- No new user-facing copy, so the 4-locale i18n parity check is unaffected.
- Comments explain the *why* only, and a deliberate ceiling is written as `shortcut: <limit>, <when to upgrade>`.

## Review Focus

Five things a reasonable person would expect to keep working, most likely first:

1. **Node-down alerts land promptly.** Today the collector runs ~3×/min, so a dead node is Telegram-alerted within ~30 s. Task 1 moves the ceiling to 5 min (still 6× better than the 30 min the released 2.1.2 had). Pinned by `TestMetricsDue`.
2. **One hung node cannot stall a collect.** Task 2 replaces a sequential 10 s + 30 s probe per node with the bounded fan-out; a node that never answers must not push the pass past the deadline. Pinned by `TestCollectMetricsFanout`.
3. **Every online user still gets a `last_online` stamp.** Task 3 batches the writes; a dropped name breaks "last seen" in the user list. Pinned by `TestTouchLastOnline`.
4. **Server Info stays live.** Task 4 stops the metrics refetch but must keep uptime/CPU/Disk refreshing on every live tick. Pinned by `SystemSection › fetches metrics history once but keeps server info live`.
5. **The dashboard stays reachable.** Task 5 moves the cert paths; if the unit does not come back on `https://0.0.0.0:2095`, the operator is locked out of a panel that fell back to plaintext localhost. Pinned by the `curl` verification step.

---

## Findings and evidence (measured on the running panel, 2026-10-26)

1. **`CollectMetrics` runs every ~20 s instead of every 30 min.** Added to `internal/panel/live_worker.go:78` and `internal/panel/traffic_worker.go:88`. `git show HEAD:` proves the only prior callers were the on-demand `POST /metrics/collect` button and a 30-minute Telegram sweep. Sample timestamps in `traffic_snapshots` read `:09` (traffic) plus `:24`, `:54` (live) — 3 per minute. The two workers call it from separate goroutines with no serialization, and `pollDue`'s idle gate protects only the snapshot, not this.
2. **`GET /api/metrics/history?hours=24` returns 811 973 bytes, uncompressed, and the Settings page refetches it on every live tick.** `web/src/pages/settings/SystemSection.tsx:63-79` fetches it inside `load`, whose effect deps include `refreshTick`. In the old tabbed Settings this tile mounted only when its tab was open; the bento layout mounts all ten.
3. **`nodeSnapshot` probes nodes sequentially with no cap or deadline** (`internal/telemetry/handler.go:445-449`): `GetNodeInfo()` at 10 s, then `GetSessions()` at 30 s, one node after another, bypassing `GatherNodes`, the fan-out semaphore and `FairShareTimeout`. One black-holed node adds up to 40 s per pass, and finding 1 made that pass run 3×/min in two goroutines.
4. **The panel fell back to plaintext localhost.** `/opt/ovmanager/.env` still points `SSL_CERTFILE`/`SSL_KEYFILE` at `/etc/letsencrypt/live/star.imkoris.info/…`, which is `root:root 0700`; the unit runs as `ovmanager`. Every start logs `legacy tls migration: mkdir …: permission denied`, then `listening on http://127.0.0.1:2095 (no TLS)`; `ss -ltnp` confirms. The migrated certs are already at `/var/lib/ovmanager/tls/`.
5. **One `UPDATE users SET last_online` per live session, per tick**, in two separate loops: `internal/telemetry/handler.go:604` (per live session) and `:419` (per active user). Invisible at 1 user, 200 transactions per tick at 200 sessions.
6. **`audit_logs` grows forever.** `internal/audit/audit.go:47` now writes a row per login and per user mutation, and the only prune (`PruneAuditLogs`) is wired to the manual cleanup endpoint. Closed by Task 1 Step 5.
7. **Bento Settings multiplies page traffic** — ten tiles mount at once, so `/security/summary`, `/server/info`, `/maintenance/backup/list` and `/metrics/history` all refetch per tick. The in-flight dedupe in `web/src/services/api.ts` only collapses requests that overlap in time, which these do not. Task 4 removes the 811 KB member; the other three are deferred, see below.
8. **`make build` never clears `internal/webfs/dist`** (`Makefile:29-30`, `cp -a web/dist/.`): 241 files / 4.7 MB staged against a current build of 104 files / 1.8 MB, all embedded into the 28.6 MB binary.
9. **`idx_audit_logs_promoted ON audit_logs(id) WHERE promoted = 0`** (`internal/db/migrate.go:394`) indexes the `INTEGER PRIMARY KEY` alias — it cannot help a query and every insert maintains it.

**Deferred, deliberately:**

- **Finding 7, the rest of the bento tiles.** After Task 4 the remaining per-tick refetches are `/security/summary?hours=8` (measured 33 ms), `/maintenance/backup/list` (1.5 ms) and `/server/info` (1.6 ms) — about 4 KB per tick against the 811 KB this plan removes. Lazy-mounting below-the-fold tiles is the right fix and is a UX change, not a performance one; it belongs with the bento design, not with this regression.
- **Finding 10** — `event_key` should be a real column so `promoteEvents`/`PruneAuditLogs` stop running `json_extract` per row. It is a schema change with a migration, and after Task 1 both run at most once per 5 minutes over a bounded candidate set.
- **Finding 12** — API responses carry no `Content-Encoding` while static assets get `.gz` siblings. Real, but it was never compressed, so it is not the regression.

---

### Task 1: One gated metrics collector

**Files:**
- Modify: `internal/telemetry/handler.go` (above `func CollectMetrics`, ~line 318)
- Modify: `internal/panel/live_worker.go:76-79`
- Modify: `internal/panel/traffic_worker.go:80-89`
- Test: `internal/telemetry/handler_test.go` (new file, same package)

**Interfaces:**
- Consumes: `CollectMetrics(db *sql.DB)` (existing, unchanged) and `PruneAuditLogs(db *sql.DB, keepDays int) int` (existing, exported from the same file).
- Produces: `CollectMetricsIfDue(db *sql.DB) bool` — runs at most one pass per `metricsEvery`, returns whether it ran. `metricsDue(now time.Time) bool` is the pure gate. Task 2 and Task 3 change the body of `CollectMetrics`; they do not change this signature.

- [ ] **Step 1: Write the failing test for the gate**

In `internal/telemetry/handler_test.go`:

```go
package telemetry

import (
	"testing"
	"time"
)

// TestMetricsDue: the first call runs, a call inside the window is skipped,
// a call at the window edge runs.
func TestMetricsDue(t *testing.T) {
	metricsLastTS = time.Time{}
	t.Cleanup(func() { metricsLastTS = time.Time{} })
	base := time.Unix(1_700_000_000, 0)

	if !metricsDue(base) {
		t.Fatal("first call must run")
	}
	if metricsDue(base.Add(time.Minute)) {
		t.Fatal("a call inside the window must be skipped")
	}
	if !metricsDue(base.Add(metricsEvery)) {
		t.Fatal("a call at the window edge must run")
	}
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /root/workspace/OVManager && go test ./internal/telemetry/ -run TestMetricsDue`
Expected: compile failure — `undefined: metricsDue`, `undefined: metricsLastTS`, `undefined: metricsEvery`.

- [ ] **Step 3: Implement the gate in `internal/telemetry/handler.go`**

Directly above `// CollectMetrics mirrors metrics.collect_metrics`, add:

```go
// metricsEvery is the collector's own cadence. shortcut: 5 min bounds the node
// probes and the history tables (288 samples/day); a node-down alert lands up
// to 5 min late. Drop to 1 min when alert latency matters more than probe load.
const metricsEvery = 5 * time.Minute

var (
	metricsLastMu sync.Mutex
	metricsLastTS time.Time
)

// metricsDue reports whether a collect is due at now, and claims the window.
func metricsDue(now time.Time) bool {
	metricsLastMu.Lock()
	defer metricsLastMu.Unlock()
	if metricsLastTS.IsZero() || now.Sub(metricsLastTS) >= metricsEvery {
		metricsLastTS = now
		return true
	}
	return false
}

// CollectMetricsIfDue runs one metrics pass at most every metricsEvery and
// reports whether it did. It is the only scheduled entry point: the panel's
// live and traffic workers must not each run a full collect.
func CollectMetricsIfDue(db *sql.DB) bool {
	if !metricsDue(time.Now()) {
		return false
	}
	CollectMetrics(db)
	return true
}
```

`sync` is already imported in this file.

- [ ] **Step 4: Run the test to verify it passes**

Run: `go test ./internal/telemetry/ -run TestMetricsDue`
Expected: PASS.

- [ ] **Step 5: Prune the audit trail from inside the collect**

`CollectMetrics` already ends with a 30-day `DELETE` sweep over the three snapshot tables. Append the audit prune to that same sweep, so finding 6 closes on the same cadence with no new scheduler:

```go
	PruneAuditLogs(db, 90)
```

`PruneAuditLogs` keeps only undelivered alerts, no-ops when the `delivered` table is missing, and its `ts` predicate is served by `idx_audit_logs_ts`. At one call per 5 minutes this is a no-op scan in practice — the point is that it runs at all, which today it does not.

- [ ] **Step 6: Replace the two worker call sites**

In `internal/panel/live_worker.go`, `func (h *Handler) liveTick` becomes:

```go
func (h *Handler) liveTick() {
	db := h.Svc.DB()
	runLiveCollect(db)
	telemetry.CollectMetricsIfDue(db)
}
```

In `internal/panel/traffic_worker.go`, `func (h *Handler) trafficTick` loses the `telemetry.CollectMetrics(db)` line and the now-unused `"github.com/anonysec/OVManager/go/internal/telemetry"` import **only if** `recordAliasCollisions` does not still use it — it does (`telemetry.RecordEvent`), so the import stays.

- [ ] **Step 7: Run the Go gate**

Run: `cd /root/workspace/OVManager && go test ./... && go vet ./... && gofmt -l .`
Expected: all PASS; `gofmt -l` prints nothing. `internal/panel/traffic_worker_test.go` counts ticks and must stay green unchanged.

- [ ] **Step 8: Commit**

```bash
git add internal/telemetry/handler.go internal/telemetry/handler_test.go internal/panel/live_worker.go internal/panel/traffic_worker.go
git commit -m "perf(telemetry): gate the metrics collector to one 5-minute cadence"
```

---

### Task 2: Bounded parallel node fan-out in the collect

**Files:**
- Modify: `internal/telemetry/handler.go:318-465` (`CollectMetrics`, `nodeSnapshot`)
- Test: `internal/telemetry/collector_test.go`

**Interfaces:**
- Consumes: `node.GatherNodes(calls []func() any, deadline time.Duration) []any`, `node.FairShareTimeout`, `node.NodeTimeout`, `node.PanelIDFor` — all existing, all already used by `CollectLiveSnapshot` at `handler.go:563-571`.
- Produces: `metricsFanoutDeadline` (package var, mirroring `liveFanoutDeadline` at `handler.go:478`) so a test can shrink it. `nodeSnapshot(n *node.Node, pid string) (map[string]any, map[string]any)` keeps its exact signature.

- [ ] **Step 1: Write the failing fan-out test**

Append to `internal/telemetry/collector_test.go`, mirroring `TestCollectLiveSnapshotFanout`:

```go
// TestCollectMetricsFanout: one node answers, one hangs past the deadline; the
// pass still completes within the deadline instead of waiting out the hung
// node's own 10 s + 30 s timeouts one after another.
func TestCollectMetricsFanout(t *testing.T) {
	old := metricsFanoutDeadline
	metricsFanoutDeadline = 300 * time.Millisecond
	t.Cleanup(func() { metricsFanoutDeadline = old })
	resetLiveState()
	conn := newCollectorDB(t)

	release := make(chan struct{})
	slow := fakeNode(t, `{"live_sessions":[]}`, release)
	t.Cleanup(func() { close(release) }) // LIFO: runs before slow.Close
	fast := fakeNode(t, `{"live_sessions":[]}`, nil)
	addNode(t, conn, 1, "fast", fast)
	addNode(t, conn, 2, "slow", slow)

	start := time.Now()
	CollectMetrics(conn)
	if elapsed := time.Since(start); elapsed > metricsFanoutDeadline {
		t.Fatalf("collect took %v, want within %v", elapsed, metricsFanoutDeadline)
	}
}
```

- [ ] **Step 2: Add `metricsFanoutDeadline` so the test compiles**

Beside `liveFanoutDeadline` (~line 478):

```go
// metricsFanoutDeadline bounds one CollectMetrics fan-out. A var so tests can
// shrink it; production uses the shared request fan-out deadline.
var metricsFanoutDeadline = node.RequestFanoutDeadline
```

- [ ] **Step 3: Run it to verify it fails on timing**

Run: `cd /root/workspace/OVManager && go test ./internal/telemetry/ -run TestCollectMetricsFanout -timeout 60s`
Expected: FAIL — `collect took 10s+, want within 300ms`. That 10 s is the sequential `GetNodeInfo` timeout on the hung node; it is the regression in one number.

- [ ] **Step 4: Rewrite the node loop in `CollectMetrics`**

Replace the `for _, id := range ids { … nodeSnapshot … }` block with the same shape `CollectLiveSnapshot` uses — a `calls` slice, one fair share computed once, one `GatherNodes` — and type each result through a two-field struct so both of `nodeSnapshot`'s returns survive the `any` round-trip:

```go
type snapshotPair struct {
	row      map[string]any
	sessions map[string]any
}
```

Loop body: skip a nil node, then `calls = append(calls, func() any { r, s := nodeSnapshot(n, pid); return snapshotPair{r, s} })`. Iterate `node.GatherNodes(calls, metricsFanoutDeadline)`, skip a result that is not a `snapshotPair`, and append to `nodeRows` / `sessionsByNode` as today. Compute the share exactly as `CollectLiveSnapshot` does, from `node.FairShareTimeout` and `node.NodeFanoutLimit`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `go test ./internal/telemetry/`
Expected: all PASS, including the pre-existing `TestCollectLiveSnapshot*` suite.

- [ ] **Step 6: Run the Go gate**

Run: `go test ./... && go vet ./... && gofmt -l .`
Expected: PASS, no output from gofmt.

- [ ] **Step 7: Commit**

```bash
git add internal/telemetry/handler.go internal/telemetry/collector_test.go
git commit -m "perf(telemetry): fan out the metrics node probes under the shared deadline"
```

---

### Task 3: Batch the `last_online` writes

**Files:**
- Modify: `internal/telemetry/handler.go:415-425` and `:598-608`
- Test: `internal/telemetry/handler_test.go`

**Interfaces:**
- Consumes: `newCollectorDB(t)` from `collector_test.go`, `users` table (`id, uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active, tag`) from `collectorSchema`.
- Produces: `touchLastOnline(db *sql.DB, names []string, stamp string)` — one statement for the whole batch; `stamp` is the caller's already-formatted `"2006-01-02 15:04:05.000000"` value so the function stays free of time formatting.

- [ ] **Step 1: Write the failing test**

```go
// TestTouchLastOnline stamps every name in one statement and leaves the rest.
func TestTouchLastOnline(t *testing.T) {
	conn := newCollectorDB(t)
	stamp := "2026-10-26 12:00:00.000000"
	if _, err := conn.Exec(`INSERT INTO users (id, name) VALUES (1, 'alice'), (2, 'bob'), (3, 'carol')`); err != nil {
		t.Fatalf("seed: %v", err)
	}

	touchLastOnline(conn, []string{"alice", "carol"}, stamp)

	var alice, bob string
	_ = conn.QueryRow(`SELECT COALESCE(last_online, '') FROM users WHERE name = 'alice'`).Scan(&alice)
	_ = conn.QueryRow(`SELECT COALESCE(last_online, '') FROM users WHERE name = 'bob'`).Scan(&bob)
	if alice != stamp {
		t.Errorf("alice last_online = %q, want %q", alice, stamp)
	}
	if bob != "" {
		t.Errorf("bob last_online = %q, want untouched", bob)
	}
}
```

`collectorSchema` has no `last_online` column; add it to that schema constant in `collector_test.go` as part of this step: `, last_online VARCHAR`.

- [ ] **Step 2: Run it to verify it fails**

Run: `go test ./internal/telemetry/ -run TestTouchLastOnline`
Expected: compile failure — `undefined: touchLastOnline`.

- [ ] **Step 3: Implement `touchLastOnline` in `internal/telemetry/handler.go`**

```go
// touchLastOnline stamps last_online for a batch of usernames in one
// statement — the collect path runs per live session, and one Exec per
// session is a write storm on SQLite's single writer.
func touchLastOnline(db *sql.DB, names []string, stamp string) {
	if len(names) == 0 {
		return
	}
	placeholders := strings.TrimSuffix(strings.Repeat("?,", len(names)), ",")
	args := make([]any, 0, len(names)+1)
	args = append(args, stamp)
	for _, n := range names {
		args = append(args, n)
	}
	_, _ = db.Exec(`UPDATE users SET last_online = ? WHERE name IN (`+placeholders+`)`, args...)
}
```

Only the `?` list is built from `len(names)`; every value is bound. `strings` is already imported.

- [ ] **Step 4: Rewire both loops**

In `CollectMetrics`, collect the active usernames into a `[]string` and call `touchLastOnline` once after the loop instead of executing per user. In `CollectLiveSnapshot` (~line 604), collect `username` values into a `map[string]bool` across all nodes first, then one `touchLastOnline` after the node loop — a user seen on two nodes must still produce one stamp, and the dedupe is why a set precedes the batch.

- [ ] **Step 5: Run the test to verify it passes**

Run: `go test ./internal/telemetry/ && go test ./... && gofmt -l .`
Expected: PASS, no gofmt output.

- [ ] **Step 6: Commit**

```bash
git add internal/telemetry/handler.go internal/telemetry/handler_test.go internal/telemetry/collector_test.go
git commit -m "perf(telemetry): one last_online write per collect instead of one per session"
```

---

### Task 4: The System tile stops refetching 811 KB per tick

**Files:**
- Modify: `web/src/pages/settings/SystemSection.tsx:62-80`
- Test: `web/src/pages/settings/SystemSection.test.tsx` (new)

**Interfaces:**
- Consumes: `apiClient.get('/server/info')`, `apiClient.get('/metrics/history?hours=24')`, `useLive().refreshTick` — all unchanged.
- Produces: none. No component or prop signature changes.

- [ ] **Step 1: Write the failing test**

Mirror `web/src/pages/Settings.refresh.test.tsx` exactly — same three `vi.mock` blocks (`../services/api`, `../context/LiveContext` with a mutable `refreshTick`, `../context/AuthContext`), same providers. Then:

```tsx
it('fetches metrics history once but keeps server info live', async () => {
  const tree = <MemoryRouter><ThemeProvider><ToastProvider><SystemSection /></ToastProvider></ThemeProvider></MemoryRouter>;
  const { rerender } = render(tree);
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith('/server/info'));

  refreshTick += 1;   // a live event
  rerender(tree);
  await waitFor(() => expect(
    (apiClient.get as any).mock.calls.filter((c: any) => c[0] === '/server/info').length,
  ).toBeGreaterThan(1));

  const metricsCalls = (apiClient.get as any).mock.calls.filter((c: any) => c[0] === '/metrics/history?hours=24');
  expect(metricsCalls).toHaveLength(1);
});
```

Mock `/server/info` and `/metrics/history` to resolve `ok({})` shapes the component already tolerates.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run src/pages/settings/SystemSection.test.tsx`
Expected: FAIL — `/metrics/history?hours=24` is called twice, once per tick.

- [ ] **Step 3: Split the load**

Keep `load` fetching only `apiClient.get('/server/info')` (its deps stay `[load, refreshTick]`). Add a separate mount-only metrics load guarded the way `GeneralSection` guards its first read — a `useRef` flag, or a `useEffect` whose deps are `[]` — that sets `trafficTotal` and `activeConns`. The 24 h sum is a background number, not a live one; the tile's live values are uptime/CPU/disk.

- [ ] **Step 4: Run it to verify it passes**

Run: `cd web && npx vitest run src/pages/settings/SystemSection.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run the frontend gate**

Run: `cd web && npm run verify`
Expected: build, tokens, i18n, RTL, eslint, tsc, vitest all green.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/settings/SystemSection.tsx web/src/pages/settings/SystemSection.test.tsx
git commit -m "perf(web): fetch the 24h metrics history once per mount, not per live tick"
```

---

### Task 5: Point the panel at the migrated certificates

**Files:**
- Modify: `/opt/ovmanager/.env` (deployed host, not the repo)
- Repo mirror: `.env.example` if it names the old Let's Encrypt path

**Interfaces:**
- Consumes: `/var/lib/ovmanager/tls/fullchain.pem` and `/var/lib/ovmanager/tls/privkey.pem` — both present, owned `ovmanager`, key mode `0600`.
- Produces: nothing in code. The panel must bind `https://0.0.0.0:2095`.

- [ ] **Step 1: Fix the two paths and the file mode**

```bash
sudo sed -i 's#^SSL_CERTFILE=.*#SSL_CERTFILE=/var/lib/ovmanager/tls/fullchain.pem#; s#^SSL_KEYFILE=.*#SSL_KEYFILE=/var/lib/ovmanager/tls/privkey.pem#' /opt/ovmanager/.env
sudo chmod 600 /opt/ovmanager/.env && sudo chown ovmanager:ovmanager /opt/ovmanager/.env
```

The mode change closes finding 11 — the file holds `NODE_ENCRYPT_KEY` and `BOT_ENCRYPT_KEY` and was `0644`.

- [ ] **Step 2: Restart and confirm the listener**

```bash
sudo systemctl restart ovmanager
ss -ltnp | grep 2095
```
Expected: `LISTEN … 0.0.0.0:2095 … ovmanager` — not `127.0.0.1`. Then:
```bash
curl -sk https://127.0.0.1:2095/api/health -o /dev/null -w '%{http_code}\n'
```
Expected: `200`. The `legacy tls migration: permission denied` line must be gone from `journalctl -u ovmanager -n 20`.

- [ ] **Step 3: Commit the example file if it changed**

```bash
git add .env.example
git commit -m "fix(install): default TLS paths to the migrated certificate location"
```

---

### Task 6: Clean the embed staging directory before copying

**Files:**
- Modify: `Makefile:29-30`

**Interfaces:**
- Consumes: `web/dist` (built or handed over by CI), `internal/webfs/dist/.gitkeep` (kept by `.gitignore` conventions so the embed resolves on a clean checkout).
- Produces: nothing in code.

- [ ] **Step 1: Replace the two recipe lines**

```make
	@rm -rf internal/webfs/dist
	@mkdir -p internal/webfs/dist
	@cp -a web/dist/. internal/webfs/dist/
```

`rm -rf` then `mkdir` because `go:embed` needs the directory to exist even when `web/dist` is empty.

- [ ] **Step 2: Verify the staged tree matches the build**

Run: `cd /root/workspace/OVManager && make build && find internal/webfs/dist -type f | wc -l && find web/dist -type f | wc -l`
Expected: the two counts are equal (today they read 241 and 104). Confirm the binary still starts: `./ovmanager --version`.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "build: clear the embedded dist before staging so stale assets stop shipping"
```

---

### Task 7: Drop the unusable audit index

**Files:**
- Modify: `internal/db/migrate.go:394`
- Test: `test/migrate_test.go`

**Interfaces:**
- Consumes: `hasIndex(t, conn, name)` (existing helper at `test/migrate_test.go:40`), `newMigrateDB(t)` (`:16`).
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```go
// TestMigrateDropsUnusableAuditIndex: an index on the rowid alias cannot serve
// a query; a database that already carries it must lose it, and a fresh one
// must never gain it.
func TestMigrateDropsUnusableAuditIndex(t *testing.T) {
	conn := newMigrateDB(t)
	if _, err := conn.Exec(`CREATE INDEX idx_audit_logs_promoted ON audit_logs(id) WHERE promoted = 0`); err != nil {
		t.Fatalf("pre-create index: %v", err)
	}
	if err := db.Migrate(conn); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	if hasIndex(t, conn, "idx_audit_logs_promoted") {
		t.Error("idx_audit_logs_promoted still present after migrate")
	}
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `go test ./test/ -run TestMigrateDropsUnusableAuditIndex`
Expected: FAIL — the index survives.

- [ ] **Step 3: Replace the CREATE with an idempotent drop**

At `internal/db/migrate.go:394`, replace the `CREATE INDEX IF NOT EXISTS idx_audit_logs_promoted …` line with:

```go
	// shortcut: this index targets the rowid alias, so it can never serve a
	// query and every insert maintained it. Drop it wherever it lingers.
	`DROP INDEX IF EXISTS idx_audit_logs_promoted`,
```

`createExtraTables` runs on every start, so existing databases self-heal and fresh ones are unaffected.

- [ ] **Step 4: Run it to verify it passes**

Run: `go test ./test/ -run TestMigrateDropsUnusableAuditIndex && go test ./...`
Expected: PASS. `TestMigrateFreshAndUpgradedConverge` compares fresh and upgraded index sets and must stay green — neither side has the index now.

- [ ] **Step 5: Commit**

```bash
git add internal/db/migrate.go test/migrate_test.go
git commit -m "db: drop the unusable audit_logs promoted index"
```

---

## After the plan

Task 1 is the regression itself; Tasks 2–4 are the amplification it caused. On the deployed panel, confirm the fix the same way the problem was found:

```bash
sqlite3 /opt/ovmanager/data/ovmanager.db \
  "SELECT COUNT(*), MAX(ts)-MIN(ts) FROM traffic_snapshots WHERE ts > strftime('%s','now')-3600;"
```

Expected after an hour: roughly 12 rows, not ~180.
