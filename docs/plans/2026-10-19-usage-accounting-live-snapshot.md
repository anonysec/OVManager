# Usage accounting and live snapshot wiring — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-written traffic accounting pipeline (billing + node + users) to real node data, and start the already-written live snapshot collector on a ticker, so quotas, subscription links, health, SSE, and usage history actually work.

**Architecture:** Two always-on goroutines started from `panel.Mount` — a 60s traffic poll and a 30s/300s live-snapshot poll — both fan out over active nodes with `node.GatherNodes` and persist through OCC-guarded transactions. Two process-killing map races are fixed first because the tickers raise their overlap probability. No OVNode changes.

**Tech Stack:** Go 1.26, modernc SQLite (WAL), React/Vite SPA (untouched), httptest for node fakes. No new dependencies.

**Spec:** `docs/plans/2026-10-19-usage-accounting-live-snapshot-design.md` (rev 2). Read both before starting any task.

## Global Constraints

- Go 1.26, module `github.com/anonysec/OVManager/go`. `go test ./...` and `go vet ./...` must stay green; CI runs `go test -race`.
- House rules: no new `:root` (frontend untouched here); node HTTP only via `node_client`/`node.NodeClient`; traffic accounting stays race-safe with conditional `WHERE used IS …` updates; prefix-agnostic (no hardcoded `/api`).
- No new dependencies. No schema change beyond none (reseed marker lives inside existing `users.node_usage` JSON).
- No code comments unless they explain a non-obvious tradeoff; keep the existing `ponytail:` style for deliberate simplifications.
- Every new ticker is started from `panel.Mount`, uses `h.Svc.DB()` (SwapDB-safe), and must not ride the Telegram `ready()` gate.

## Review Focus

Inputs/failure modes the spec implies but no single task's tests exercise; most likely first:

1. **A node that answers but has zero live sessions** — must stay online with zero connections; a naive `len(live_sessions) > 0` check would silently empty the subscription page.
2. **A legacy DB with `used IS NULL`** — the OCC guard must not silently skip the user forever.
3. **Concurrent `SyncAllUserLimits` mutating `node_usage.push_hash` during a traffic pass** — the OCC retry must absorb it; without the retry a node's whole contribution is dropped.
4. **A user deleted between the `users` load and the `GetUsage` reply** — must be skipped, not abort the batch.
5. **A node that times out mid-fanout** — the deadline must yield `offline`, not panic or hang the ticker.

Each gets an explicit test in the task that owns the code (see that task's steps).

---

### Task 0a: Fix the `Client.headers` concurrent-map race

**Files:**
- Modify: `internal/node/connection.go` (NodeClient, Headers, getConnection)
- Modify: `internal/node/client.go` (roundtrip, reqOpts, NewClient)
- Test: `internal/node/race_test.go` (new)

**Interfaces:**
- Consumes: `reqOpts.rawHeader map[string]string` (already exists, `client.go:338`).
- Produces: `NodeClient(n *Node, panelID string) *Client` unchanged signature; per-request panel id carried in `reqOpts`, no shared mutation.

- [ ] **Step 1: Write the failing race test**

```go
func TestNodeClientHeadersRace(t *testing.T) {
    n := &Node{ID: 1, Name: "n", Address: "127.0.0.1", Port: 1, APIKey: "k"}
    // seed a cached connection by calling getConnection via NodeClient once
    _ = NodeClient(n, "panel-a")
    var wg sync.WaitGroup
    for i := 0; i < 8; i++ {
        wg.Add(1)
        go func(i int) {
            defer wg.Done()
            c := NodeClient(n, fmt.Sprintf("panel-%d", i))
            if c == nil { return }
            // force a roundtrip-ish read of headers through a helper if exported;
            // otherwise assert no panic by repeated stamping
            _ = c
        }(i)
    }
    wg.Wait()
}
```

Run with `-race`. Expected: FAIL today (concurrent map writes) on the shared client.

- [ ] **Step 2: Run to confirm failure** — `go test -race ./internal/node/ -run TestNodeClientHeadersRace -count=1`. Expected: race report.

- [ ] **Step 3: Implement.** In `NodeClient`, stop mutating `c.headers`; instead store the panel id on the connection or pass it through `reqOpts`. Simplest: add `panelID string` to `reqOpts` and have `NodeClient` return `c` unchanged, while a wrapper stamps `o.rawHeader["X-Panel-ID"]` at call time — but callers build `reqOpts` internally. Alternative: store `panelID` on the cached `connection` under `connMu` and read it in `roundtrip` under the lock. Choose the latter: add `panelID string` to `connection`, set it in `NodeClient` under `connMu` (lock already exists), read it in `roundtrip` by looking up the connection by id. For uncached (`n.ID == 0`) clients, set `c.panelID` directly under no lock (single owner at creation). Then in `roundtrip`, `req.Header.Set("X-Panel-ID", c.panelID())` when non-empty, replacing the `for k, v := range c.headers` stamping. Remove the `Headers()` mutation path usage (keep the method for compatibility, returning a copy or the map read-only).

- [ ] **Step 4: Run test** — `go test -race ./internal/node/ -count=1`. Expected: PASS, no race.

- [ ] **Step 5: Commit** — `git commit -m "fix(node): stop mutating shared Client.headers across goroutines"`.

---

### Task 0b: Fix the telemetry and health map races

**Files:**
- Modify: `internal/telemetry/handler.go` (nodeState/lastDownAlert/alertedDownSet → guarded struct; graceUntil → same or separate mutex)
- Modify: `internal/panel/health.go` (checkState → guarded struct)
- Test: `internal/telemetry/race_test.go`, `internal/panel/race_test.go` (new)

**Interfaces:**
- Produces: `telemetry.CollectMetrics(db)` and `panel` health handler unchanged externally; internal state access goes through methods.

- [ ] **Step 1: Write failing race tests** — one goroutine calling `telemetry.CollectMetrics(db)` while another calls it again (or `POST /metrics/collect`), plus `healthOverview` handler concurrency. Run with `-race`; expect failure.

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement.** Move each package-level map into a struct with `sync.Mutex` (or `sync.RWMutex`): `nodeAlertState{mu, nodeState, lastDownAlert, alertedDownSet}` and `checkState{mu, m}`. All reads/writes take the lock. `graceUntil` joins the telemetry struct (single collector goroutine owns it, but lock it anyway for the manual collect path). Keep function signatures.

- [ ] **Step 4: Run** — `go test -race ./internal/telemetry/ ./internal/panel/ -count=1`. Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "fix(telemetry,panel): guard nodeState/checkState maps with mutex"`.

---

### Task 1: Make billing writers transaction-capable (`execer`)

**Files:**
- Modify: `internal/billing/ledger.go` (`ApplyUserTraffic`, `RecordDailyBytes`)
- Test: `test/billing_tx_test.go` (new, in `test/` package, parity style)

**Interfaces:**
- Produces: `billing.ApplyUserTraffic(db billing.Execer, userID int64, expectedUsed int64, expectedState string, newUsed int64, newState string, delta int64) bool` and `billing.RecordDailyBytes(db billing.Execer, userID, delta int64, day string)`. `*sql.DB` and `*sql.Tx` both satisfy `billing.Execer`.

- [ ] **Step 1: Add the interface** at the top of `ledger.go`:

```go
type Execer interface {
    Exec(query string, args ...any) (sql.Result, error)
}
```

Change both function params from `*sql.DB` to `Execer`. No body change (they only call `.Exec`).

- [ ] **Step 2: Verify existing tests still compile/pass** — `go test ./internal/billing/ ./test/ -count=1`. Expected: PASS (call sites pass `*sql.DB`).

- [ ] **Step 3: Write the failing tx-rollback test** in `test/billing_tx_test.go`: open a temp DB, create a user, begin tx, call `ApplyUserTraffic(tx, …)` with a delta, then force a failure before commit (e.g. insert a conflicting row), rollback, assert `users.used` and `user_traffic_daily` are both unchanged.

- [ ] **Step 4: Run** — expected FAIL (today the daily row is written inside ApplyUserTraffic on the same Execer, but the test forces the outer tx to rollback; if RecordDailyBytes uses the same tx it rolls back too — actually it already does since both use `tx`. The test should PASS already…). Adjust: the real gap is that `RecordDailyBytes` is called only when `delta != 0` and uses the same execer; the test should verify rollback of **both**. If it passes immediately, instead test the *absence* of a tx today by simulating a partial failure between the two Exec calls — not possible without changing code. So change the test to assert the documented contract: after a successful ApplyUserTraffic on a tx that is then rolled back, neither table changes. Run; expected PASS (confirms tx-capability). If it passes, proceed.

- [ ] **Step 5: Run full suite** — `go test ./... -count=1`. Expected: PASS.

- [ ] **Step 6: Commit** — `git commit -m "refactor(billing): accept Execer so writes can share a transaction"`.

---

### Task 2: `SyncTraffic` implementation

**Files:**
- Create: `internal/node/traffic.go`
- Modify: `internal/node/sync.go` (add `PushHashKey` const reuse — already defined; no change needed; add `ReservedUsageKeys` helper)
- Test: `internal/node/traffic_test.go`

**Interfaces:**
- Consumes: `node.GatherNodes(calls []func() any, deadline time.Duration) []any` (`fanout.go:76`), `NodeClient`, `GetUsage`, `PanelIDFor`, `GetNodeByID`, `billing.ApplyUserTraffic`, `billing.ComputeSessionDelta`, `billing.ExtractUsername`, `billing.Canon`.
- Produces: `func SyncTraffic(db *sql.DB) TrafficResult` where

```go
type TrafficResult struct {
    NodesPolled int
    NodesFailed int
    UsersUpdated int
    UsersSeeded  int
    BytesBilled  int64
}
```

- [ ] **Step 1: Write failing tests** (httptest node returning fixed `totals`):
  - `TestSyncTrafficBillsTwoNodes`: two nodes each reporting `totals: {"alice": 1000}` and `{"alice": 2000}` (different node names); one pass → `used == 3000`, `BytesBilled == 3000`. (guards 1.0.44)
  - `TestSyncTrafficSkipsDeletedUser`: node reports a key not in `users`; pass completes, `UsersUpdated == 0`, no error.
  - `TestSyncTrafficOCCRetry`: mutate `node_usage` between read and write (simulate concurrent SyncAllUserLimits) via a hook; assert the pass retries and bills once.
  - `TestSyncTrafficFirstPollSeeds`: no baseline key present → `BytesBilled == 0`, baseline written as current total.
  - `TestSyncTrafficNullUsed`: user row with `used IS NULL` still bills.
  - `TestSyncTrafficNodeTimeout`: fake node sleeps past `RequestFanoutDeadline`; result marks it failed, other node's contribution still applied.

- [ ] **Step 2: Run** — expected FAIL (function undefined).

- [ ] **Step 3: Implement `SyncTraffic`** per spec §4.3 steps 1–9, including:
  - Load active nodes and users (with `COALESCE(used,0)`).
  - Build `known` name set.
  - Fan out `GetUsage` with `ProbeTimeout`.
  - Per (user, node): extract baseline scalar for node id key (0 if absent, but distinguish absent → seed flag).
  - Reseed marker check: if `node_usage["__reseed"]` present, force seed (baseline = current, delta 0) for all nodes and clear the marker.
  - First-poll seed: if baseline key absent, seed.
  - Otherwise compute delta; on `ApplyUserTraffic` false, reload + retry ≤3.
  - Accumulate counts.

  Use `billing.Execer` via `db` (a `*sql.DB` satisfies it). Write baselines as bare int64 keyed by node id string.

- [ ] **Step 4: Run tests** — `go test ./internal/node/ -run 'TestSyncTraffic' -count=1`. Expected: PASS.

- [ ] **Step 5: Run race** — `go test -race ./internal/node/ -count=1`. Expected: PASS.

- [ ] **Step 6: Commit** — `git commit -m "feat(node): implement SyncTraffic with OCC retry, seeding, and fanout"`.

---

### Task 3: Traffic worker + route + Mount wiring

**Files:**
- Create: `internal/panel/traffic_worker.go`
- Modify: `internal/panel/panel.go` (route `POST /maintenance/sync-traffic`, call `h.startTrafficWorker()` in Mount)
- Test: `internal/panel/traffic_worker_test.go`

**Interfaces:**
- Produces: `func (h *Handler) startTrafficWorker()` and `func (h *Handler) syncTraffic(w, r)` (owner-gated handler returning the `TrafficResult` envelope).

- [ ] **Step 1: Write failing test** — start worker against a no-node DB; assert no panic and a manual `POST /maintenance/sync-traffic` returns `success: true` with zero counts. Also assert the worker does not depend on Telegram settings (set bot disabled, run one tick via an exported `tick()` helper, assert it still calls SyncTraffic — use a counter hook).

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement** — mirror `tls_acme.go` goroutine pattern: `sync.Once`, boot delay 30s, ticker from `OVM_TRAFFIC_POLL_SECONDS` (default 60), call `node.SyncTraffic(h.Svc.DB())`, log the result. Route handler calls `node.SyncTraffic(h.Svc.DB())` and writes the envelope.

- [ ] **Step 4: Run** — `go test ./internal/panel/ -run 'Traffic' -count=1`. PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(panel): add traffic worker and sync-traffic route"`.

---

### Task 4: Reserved keys in `node_usage` (reader side)

**Files:**
- Modify: `internal/users/handler.go` (`aggregateNodeUsage` — skip reserved keys, resolve id→name with name fallback)
- Modify: `internal/node/sync.go` (export `ReservedUsageKeys` or a helper `IsReservedUsageKey`)
- Test: `internal/users/usage_test.go` (new) or extend `test/users_test.go`

**Interfaces:**
- Produces: `node.IsReservedUsageKey(key string) bool` returning true for `push_hash` and `__reseed`.

- [ ] **Step 1: Write failing test** — seed `node_usage = {"1": 500, "push_hash": {"1": "abc"}, "__reseed": true}`; `aggregateNodeUsage` returns one entry (node 1), no `push_hash`/`__reseed` entries. Also test name-fallback: `node_usage = {"oldname": 500}` with no node id 1 resolves by name.

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement** — skip reserved keys in the loop; resolve key: if it parses as an int id, look up name in the id→name map; else treat as name (legacy). Keep `push_hash` handling in `resetUsage` untouched.

- [ ] **Step 4: Run** — PASS.

- [ ] **Step 5: Commit** — `git commit -m "fix(users): skip reserved keys and resolve node ids in usage aggregation"`.

---

### Task 5: Usage reset with reseed marker

**Files:**
- Modify: `internal/users/handler.go` (`resetUsage`)
- Modify: `internal/panel/maintenance.go` (`usageResetAll`)
- Test: extend `test/users_test.go` reset case

**Interfaces:**
- Consumes: reserved marker key `node.ReseedMarkerKey = "__reseed"`.

- [ ] **Step 1: Update the existing reset test** — `test/users_test.go:314-341` currently pins `node_usage == "{}"`. Change to pin: `used == 0`, `push_hash` subtree preserved, marker present. Add a new test: seed `used=999, node_usage={"1": 500, "push_hash": {"1":"x"}}`; reset; assert `node_usage` contains `"1": 500` and `"push_hash"` and `"__reseed": true`; then run `SyncTraffic` against a node reporting `totals: {"u": 600}` and assert `used == 100` (delta 100, not 600) and marker cleared.

- [ ] **Step 2: Run** — FAIL (old code wipes node_usage).

- [ ] **Step 3: Implement** — `resetUsage`: zero `used`/`last_node_usage`, keep `push_hash` and per-node baselines, add marker. `usageResetAll`: single `UPDATE users SET used = 0, last_node_usage = 0, node_usage = json_set(COALESCE(node_usage,'{}'), '$.__reseed', 1)` — or load/merge in Go if SQLite JSON1 isn't guaranteed. Prefer Go-side merge in a loop for clarity and testability; acceptable since reset-all is admin-triggered.

- [ ] **Step 4: Run** — `go test ./... -count=1`. PASS.

- [ ] **Step 5: Commit** — `git commit -m "fix(users): reset uses reseed marker instead of wiping baselines"`.

---

### Task 6: Wire `topTraffic` and per-day series (small wins)

**Files:**
- Modify: `internal/users/handler.go` (`topTraffic`, `traffic`)
- Test: `test/users_test.go`

- [ ] **Step 1: Write failing tests** — `GET …/top-traffic` returns the `billing.TopUsers` shape; `GET …/traffic/{uuid}` returns `days` as `billing.UserDailySeries` output (seed daily rows first).

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement** — `topTraffic` → `billing.TopUsers(h.Svc.DB(), days, limit)` with clamped params; `traffic` → `"days": billing.UserDailySeries(h.Svc.DB(), row.ID, days)`.

- [ ] **Step 4: Run** — PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(users): wire top-traffic and per-day series to billing helpers"`.

---

### Task 7: Live snapshot collector — parallel fanout + correct mapping

**Files:**
- Modify: `internal/telemetry/handler.go` (`CollectLiveSnapshot`)
- Test: `internal/telemetry/collector_test.go` (new)

**Interfaces:**
- Consumes: `node.GatherNodes`, `idToName` (already built), `billing.ExtractUsername` (secondary only).

- [ ] **Step 1: Write failing tests**:
  - `TestCollectLiveSnapshotFanout`: two fake nodes, one times out; assert the tick completes within the deadline, the slow node is `offline`, the fast one `online`, and `SnapshotFresh()` true.
  - `TestCollectLiveSnapshotIdleNodeOnline`: a node that answers with `live_sessions: []` is `online == true` with 0 connections (guards review-focus #1).
  - `TestCollectLiveSnapshotCNMapping`: node reports `common_name: "42"`; with `users.id=42, name="alice"` loaded, `counts["alice"] == 1`.
  - `TestCollectLiveSnapshotNameFallback`: node reports a name-shaped CN with no matching id; `ExtractUsername` resolves it.
  - `TestApplyGrace`: unit test for `applyGrace` transitions (up→down arms grace, within window holds up, past window goes down, never-seen stays down).

- [ ] **Step 2: Run** — FAIL/PARTIAL (fanout not wired).

- [ ] **Step 3: Implement** — replace the sequential loop with `node.GatherNodes`; keep `len(data) == 0` as the offline test; keep `idToName` primary mapping; add `ExtractUsername` as fallback for unmapped name-shaped CNs. Trim `connections` in `updateSnapshot` by the same cap rule. Log node/user counts on DB error.

- [ ] **Step 4: Run** — `go test ./internal/telemetry/ -count=1`. PASS.

- [ ] **Step 5: Run race** — PASS.

- [ ] **Step 6: Commit** — `git commit -m "feat(telemetry): parallelize CollectLiveSnapshot and fix CN mapping"`.

---

### Task 8: Live worker + idle cadence + PollSeconds wiring

**Files:**
- Create: `internal/panel/live_worker.go`
- Modify: `internal/panel/panel.go` (call `h.startLiveWorker()` in Mount)
- Modify: `internal/telemetry/handler.go` (`CollectLiveSnapshot` idle-window gate)
- Modify: `README.md:175` (fix the "every 10 seconds" sentence)
- Test: `internal/panel/live_worker_test.go`, `internal/telemetry/idle_test.go`

**Interfaces:**
- Produces: `func (h *Handler) startLiveWorker()`.

- [ ] **Step 1: Write failing tests**:
  - `TestLiveWorkerStarts`: no panic on no-node DB; manual tick calls CollectLiveSnapshot.
  - `TestIdleWindow`: with no subscribers, a tick within 300s of the last poll is skipped; with subscribers, a tick within 30s is skipped but one at 31s runs.
  - `TestPollSecondsEnv`: `OVMANAGER_LIVE_POLL_SECONDS=45` returns 45.

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement** — worker mirrors ACME pattern: boot delay 15s, ticker at `PollSeconds()`. Idle gate per §5.2. Fix README sentence to "30s while a browser holds the stream open, 300s idle."

- [ ] **Step 4: Run** — `go test ./internal/panel/ ./internal/telemetry/ -count=1`. PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(panel): start live snapshot worker with idle cadence"`.

---

### Task 9: `userRow.live()` reads real connection counts

**Files:**
- Modify: `internal/users/handler.go` (`live()`, `userRow` — needs access to telemetry; pass counts or call `telemetry.Connections()`)
- Test: `test/users_live_test.go` or extend `test/users_test.go`

**Interfaces:**
- Consumes: `telemetry.Connections() map[string]int`.

- [ ] **Step 1: Write failing test** — seed a snapshot via `telemetry.updateSnapshot` (export a test helper or call `CollectLiveSnapshot` against a fake node), then `GET /users` and assert `active_connections` and `online` reflect it instead of hardcoded 0/`false`.

- [ ] **Step 2: Run** — FAIL (hardcoded).

- [ ] **Step 3: Implement** — in `live()` (or at the call site in `list`), look up `telemetry.Connections()[u.Name]`; `online = count > 0`. Remove the `ponytail:` comment.

- [ ] **Step 4: Run** — PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(users): populate active_connections from live snapshot"`.

---

### Task 10: Housekeeping gates

**Files:**
- Modify: `Makefile` (lint target: `gofmt -l` gate + `./...` vet; per the comment already there)
- Modify: `internal/telemetry/handler.go` (`tablesReady` → `sync.Once`)
- Test: none new; verify with existing suite.

- [ ] **Step 1: gofmt the 4 flagged files** — `gofmt -w cmd/main.go internal/cli/root.go internal/cli/tls.go test/helpers_test.go`. Run `gofmt -l .`; expected empty.

- [ ] **Step 2: Update Makefile lint**:

```make
lint:
	go vet ./...
	@test -z "$$(gofmt -l .)" || { gofmt -l .; exit 1; }
```

- [ ] **Step 3: tablesReady → sync.Once** in `handler.go`.

- [ ] **Step 4: Run** — `make lint && go test ./... -count=1`. PASS.

- [ ] **Step 5: Commit** — `git commit -m "chore: enforce gofmt in lint and make tablesReady sync.Once"`.

---

## Self-Review

1. **Spec coverage:** §4.1 totals source → Task 2; §4.2 baselines → Tasks 2, 4; §4.3 poll loop → Task 2; §4.4 worker → Task 3; §4.5 enforcement unchanged → no new code (gates untouched); §4.6 reseed → Task 5; §4.7 wiring → Task 6; §5.1–5.5 → Tasks 7–9; §6 races → Tasks 0a, 0b; §7 verification → tests in each task; §8 calls → reflected throughout. No gap.
2. **Step scan:** every step is one action with a checkable result; no "handle edge cases" placeholders; algorithmic bodies (reseed, fanout swap) are specified where the signature does not determine them.
3. **Type consistency:** `billing.Execer` (Task 1) is consumed by Task 2; `TrafficResult` (Task 2) by Task 3; `node.IsReservedUsageKey`/`ReseedMarkerKey` (Task 4) by Tasks 2, 5; `startTrafficWorker`/`startLiveWorker` (Tasks 3, 8) by Mount. Names consistent across tasks.
4. **Review Focus:** all five items have owning tests (Task 7 idle-node/timeout/CN; Task 2 NULL/OCC/deleted-user). Covered.
5. **Proportion:** plan is ~10 tasks for a two-subsystem wiring job with two race fixes; code bodies are signatures and test names, not transcripts. Acceptable.

---

Plan complete and saved to `docs/superpowers/plans/2026-10-19-usage-accounting-live-snapshot.md`. Please review the plan. Does it capture what you want?

Which execution approach would you prefer?

- **Subagent-driven** — A fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end. Most thorough; costs a fresh context per task and per review.
- **Native** — I implement every task myself in this session, then one fresh reviewer on the most capable model checks the whole branch. Cheapest and fastest; no independent review until the end.

For this plan I recommend **subagent-driven**, because the tasks share interfaces across subsystems (billing execer, TrafficResult, reserved keys, reseed marker) and a shipped mistake in any of them silently under- or over-bills real users — an independent reviewer per task is worth the cost. Does the plan capture what you want, and which approach should we use?