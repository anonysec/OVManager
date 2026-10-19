# Design: traffic accounting (C1) and live snapshot (C5) wiring

Date: 2026-10-19
Status: draft for approval
Rev 2: corrected after builder check (baseline key, reset semantics, CN mapping, offline criterion, NULL guard)
Scope: `/root/workspace/OVManager` (Go panel), node contract in `/root/workspace/OVNode` (read-only; no node changes).

## 1. Why

Two subsystems are written, tested in isolation, and never called. Nothing here is a missing edge case; both features are structurally absent:

- **Traffic accounting.** `internal/billing` has the full pipeline (`ComputeSessionDelta`, `Canon`, `ExtractUsername`, `ApplyUserTraffic`, `RecordDailyBytes`, `WriteLedgerBatch`, `UserDailySeries`, `TopUsers`), and `internal/node/sync.go:24` has `GetUsersUsedTraffic` as a two-line stub. **No production code calls any of the writers.** The only writes to `users.used` are resets to zero (`internal/panel/maintenance.go:669`, `internal/users/handler.go:446`). Every quota gate therefore reads a column that never grows: OVPN download (`internal/node/management.go:1055`), subscription (`internal/panel/sub.go:315`), `activationBlocked` (`internal/users/handler.go:664`), Telegram quota events (`internal/notify/telegram.go:226`). Users consume unlimited traffic while the panel reports compliance, and `user_traffic_daily` / `traffic_ledger` stay empty so top-traffic and per-day history can never show data.
- **Live snapshot.** `internal/telemetry.CollectLiveSnapshot` (`handler.go:479`) has zero callers; it is the only writer of the snapshot via `updateSnapshot` (`stream.go:164`). `SnapshotFresh()` is therefore permanently false, so the public subscription page emits **zero node links** (`internal/panel/sub.go:196-207`), the health checklist is stuck on "live data is stale" (`internal/panel/health.go:198-200`), the collector-driven SSE `nodes` / `users`-connections events never publish (maintenance delete and reset-usage do publish `users` frames today, `internal/panel/maintenance.go:652,675`), and `userRow.live()` hardcodes `active_connections: 0` (`internal/users/handler.go:114-119`).

Both are one missing ticker plus a handful of unwired call sites. `README.md:175` already documents the intended live behaviour, and CHANGELOG 1.0.44/1.0.45/1.6.0 document the multi-node billing bugs this design must not reintroduce.

## 2. Goals

C1:

1. Panel-side `users.used` grows from node-reported traffic, summed across **all** nodes, on a fixed cadence.
2. Multi-node correctness: node A's tick must never discard node B's contribution (CHANGELOG 1.0.44 regression).
3. Per-user isolation: an unknown/deleted user, a slow node, or a node error must not abort the batch (CHANGELOG 1.0.45 regression).
4. `user_traffic_daily` grows per day, so `UserDailySeries` / `TopUsers` return real data.
5. Enforcement stays where it already is (existing gates), with bounded lag and no mid-session kill.
6. A usage reset never re-bills bytes the panel has already counted.

C5:

1. Snapshot refreshes on a ticker independent of Telegram configuration and of browser presence (with a cheaper idle cadence).
2. Subscription links, health checklist, SSE events and `userRow.live()` all read live data.
3. No DB schema change, no SSE payload change, no change to what "node online" means.

## 3. Non-goals

- No mid-session disconnect when a quota is hit (no auto-kick). The existing sweep only acts on expiry/active state.
- No node-side usage-bank zeroing as part of a panel reset. Node `reset-usage` (`POST /sync/user/{uid}/reset-usage`, OVNode `users.py:89-102` → `store.py:340`) zeroes only the bank; the panel would still have to reason about live-session bytes. The reseed mechanism in §4.6 makes it unnecessary; a node's own display keeps accumulating, which the panel does not surface.
- No changes to OVNode. Nothing needed: `GET /sync/usage` already returns cumulative per-user bytes and a read never resets counters.
- No new SSE event names, payload shapes or `cap` changes (`test/telemetry_test.go:153-194` pins the framing).
- No per-user session detail in the panel API beyond a count (the `GET /users/{uuid}/sessions` stub stays a stub; the node reports no session start times).
- No `traffic_ledger` backfill redesign, no ledger retention change.
- No fix for the missing `SetMaxOpenConns`, the sequential `CollectMetrics` loop, or the Telegram `ready()` gate on `CollectMetrics` — noted as follow-ups, not part of this work.

## 4. C1 — traffic accounting

### 4.1 Source of truth: the node's cumulative `totals`

`GET /sync/usage` (OVNode `backend/api/routes/stats.py:52`, OVNode `backend/openvpn/users.py:369-406`) returns:

```json
{"users": {"<name|cn>": <live bytes>},
 "sessions": {"<cn|name>": {"<ip:port>": <live bytes>}},
 "totals": {"<name|cn>": <banked + live bytes, monotonic>}}
```

`totals` is cumulative lifetime per user on that node: banked completed sessions plus the live ones. A read never zeroes anything; only `POST /sync/user/{uid}/reset-usage` zeroes the **bank**, and live bytes keep flowing.

Use `totals`, not `sessions`, as the delta source: `sessions` only contains *live* sessions, so bytes belonging to a session that ended between two polls exist only in the bank, and a per-session map would silently drop them. This is exactly the `sessions == nil` (legacy total) branch of `billing.ComputeSessionDelta` (`internal/billing/ledger.go:234-247`):

```
delta = cur >= prev ? cur - prev : cur
new_state = cur
```

Note for the builder: do **not** pass the raw node `sessions` map to `ComputeSessionDelta`'s per-session branch. Its values are nested objects (`{"ip:port": bytes}`), while the helper compares `toI64(value)` per key, which yields 0 for a map — that branch would bill zero forever. The flat-map golden cases in `test/testdata/billing_golden.json` are the only shape it supports today.

### 4.2 Where the per-node baseline lives

`users.node_usage` is a JSON object that already holds two things:

- reserved key `push_hash` → `{ "<node id>": "<sha256>" }`, maintained by `internal/node/sync.go:205-234` with its own mini-OCC (`UPDATE … WHERE id = ? AND COALESCE(node_usage,'{}') = ?`, `sync.go:230`) that merges only that key and preserves siblings;
- per-node accounting state, which `aggregateNodeUsage` (`internal/users/handler.go:614-654`) reads, accepting either a bare int or `{"total": N}`. Its node lookup is name-based today (`SELECT name, id FROM nodes`).

Decision: key baselines by **node id** (decimal string), the same key space `push_hash` already uses. Values are bare int64 totals.

- A node **rename** (`internal/node/management.go:478-496`) then cannot orphan a baseline. With name keying, a rename freezes the old key and the new key starts at 0, re-billing the node's entire cumulative total as one delta — the 1.0.44 failure mode. This is the reason to depart from the existing name-keyed reader.
- `aggregateNodeUsage` must resolve id → name, keeping a name-key fallback so legacy/importer rows still render. It currently has no filter for the reserved keys either: once a sync runs, per-node usage lists show a fake node called `push_hash` with 0 bytes, and the new `reseed` marker (§4.6) would appear the same way. Skip reserved keys (`internal/node.PushHashKey` and the new marker key) when enumerating nodes.
- `ComputeSessionDelta`'s legacy branch ignores a map-shaped `prevState` (`ledger.go:234-239`: a dict leaves `prevInt = 0`). The writer must extract the scalar for the node before calling, or it books the full total every tick. Passing the raw entry is a silent 100%-overbilling bug — the single easiest way to get this wrong.

### 4.3 Poll loop

New file `internal/node/traffic.go`:

```
SyncTraffic(db *sql.DB) map[string]any     // one pass over all active nodes
```

Per pass:

1. Load `nodes` where `status = 1` (id, name); load `users` (id, name, `COALESCE(used,0)`, `node_usage`); build the known-name set for `ExtractUsername`.
2. `node.GatherNodes(calls, node.RequestFanoutDeadline)` (`internal/node/fanout.go:76`) — one call per node, each `NodeClient(n, PanelIDFor(db)).GetUsage(node.ProbeTimeout(n))`. A node that times out or errors contributes nothing and does not abort the pass.
3. Per node, per reported key: `billing.ExtractUsername(key, n.Name, known)` → panel username → user row. Unknown/deleted user ⇒ skip (1.0.45 regression).
4. Per (user, node): read the scalar baseline for the node's **id** from the user's `node_usage` (absent ⇒ no baseline: see the first-poll rule below), call `ComputeSessionDelta(nil, baseline, curTotal)`, then persist.
5. Persist with the OCC contract: `newUsed = coalesce(used,0) + delta`, `newState` = `node_usage` with `node_usage[nodeID] = curTotal` written back. On `false` from `ApplyUserTraffic`, **reload the row and retry** (up to 3 attempts): the write is guarded on the row still holding the loaded values precisely because `SyncAllUserLimits` merges `push_hash` into the same JSON concurrently. Dropping the retry is the second way to lose a node's whole contribution (1.0.44).
6. Wrap the update plus its daily row in **one transaction** so `users.used` and `user_traffic_daily.bytes` cannot disagree. Minimal change: `ApplyUserTraffic` currently takes `*sql.DB` and calls `RecordDailyBytes` outside any tx (`ledger.go:260-276`). Give both an `execer` interface (the pattern already exists in `internal/db/migrate.go`) so they accept `*sql.DB` or `*sql.Tx` without changing existing call sites or the golden tests.
7. **NULL guard fix (required).** The production schema has `used BIGINT` nullable, added by `reconcileColumns` as a bare `ALTER TABLE … ADD COLUMN used BIGINT` (`internal/db/migrate.go:235`, `375-394`), so an upgraded DB can hold `NULL`. `used IS ?` is false for `NULL IS 0` in SQLite: such a user would fail all 3 retries and be silently skipped on every tick, forever. Change both the load and the guard to the COALESCE dialect `SyncAllUserLimits` already uses: load `COALESCE(used,0)`, guard `COALESCE(used,0) IS ? AND COALESCE(node_usage,'{}') IS ?`. Aligning the two OCC dialects is worth doing on its own.
8. **First poll must seed, not bill.** A node with no stored baseline returns `prev = 0`, so the helper bills its whole cumulative total — every user's entire node history landing as one delta on upgrade. When the baseline key is absent for that node (or the reseed marker is set, §4.6), write `node_usage[nodeID] = curTotal` with `delta = 0`. Only an existing baseline produces billing.
9. Do not write `traffic_ledger` rows in this pass. The ledger is an audit trail with `UNIQUE (user_id, ts, kind, node_id)` and a `ts` that has no natural tick-unique value; keeping it out of the hot loop avoids a new insert-conflict source. Ledger writing stays as designed (callable), noted as a follow-up if audit demands it.

Result shape: counts of nodes polled/failed, users updated, users seeded, bytes billed — returned for the log line and the manual trigger.

### 4.4 Cadence and where the ticker lives

New `internal/panel/traffic_worker.go`, pattern copied from `internal/panel/tls_acme.go` (`sync.Once` + one goroutine + `SwapDB`-safe use of `h.Svc.DB()`), started from `Mount` next to `startACMEWorker()` / `startTelegramWorker()` (`internal/panel/panel.go:111,120`).

- Default cadence 60s, override `OVM_TRAFFIC_POLL_SECONDS`; boot delay 30s so restores/`SwapDB` settle first.
- **Must not** ride `notify.Worker.Tick`: that returns early unless a Telegram bot is configured (`internal/notify/telegram.go:317`), which would leave quota accounting dead on every bot-less install — the same class of bug being fixed.
- Manual trigger: `POST /maintenance/sync-traffic` (owner-gated), beside the existing `POST /maintenance/sync-limits` (`internal/panel/panel.go:77-83`), returning the result envelope.
- Node-side rate limit is 120 req/60s per client IP, 600/60s global; one `GET /sync/usage` per node per 60s is far inside it.

### 4.5 Enforcement semantics (my call)

- Unchanged gates, unchanged messages: OVPN download 403 (`internal/node/management.go:1055`), subscription link withheld (`internal/panel/sub.go:315`), `activationBlocked` on activate/update, Telegram quota event.
- Lag: at most one poll interval (default 60s) plus fanout deadline. Enforcement is checked at config-download time, so a user mid-session is not cut off; the next download is refused.
- No auto-disconnect. If that is wanted later it is a one-line call to the existing `kickUserNodes` (`internal/users/sweep.go:142-172`) inside the quota predicate — deliberate omission.

### 4.6 Usage reset: reseed, do not wipe, do not re-bill

`reset-usage` (`internal/users/handler.go:432-451`) preserves `push_hash` but drops every per-node baseline. With a cumulative-total source, the obvious alternative — keep the old baseline — double-bills on the next tick: after a node-side bank reset, `totals` still contains the bytes of every **live** session, so the rollback branch (`cur < prev ⇒ delta = cur`) books the live session's full byte count, which the panel already counted before the reset. (The earlier draft of this document claimed that number was "near zero"; it is not — it is whatever the live session has transferred, potentially GBs.)

Decision: an explicit **reseed marker**.

- Panel reset zeroes `used`/`last_node_usage`, keeps every per-node baseline and `push_hash`, and sets a reserved marker inside `node_usage` (e.g. `__reseed`) — one `UPDATE`, no node calls.
- On the next traffic pass, a user carrying the marker takes the seeding path for **all** nodes (§4.3 step 8): each baseline is set to that node's current total with `delta = 0`, then the marker is cleared — inside the same OCC-retried transaction, so a concurrent write cannot lose the flag.
- Result: bytes after the reset are billed normally; nothing before it is billed twice; an unreachable node is handled on a later tick without any special case. No node-side coordination, no race between a bank reset and a totals read.

`usageResetAll` (`internal/panel/maintenance.go:660-677`) wipes `node_usage` wholesale today, destroying `push_hash` (so every limit is re-pushed) and dropping baselines. Align it with the per-user path: zero `used`, keep `node_usage`, set the marker for every user in the same `UPDATE`. `last_node_usage` is a legacy aggregate no longer used as a delta source; keep writing 0 on reset for shape stability.

### 4.7 Small wiring wins in the same change

Both helpers are implemented and golden-tested; the endpoints just return placeholders:

- `topTraffic` (`internal/users/handler.go:160-162`) → `billing.TopUsers(db, days, limit)`.
- `traffic` per-day series (`internal/users/handler.go:600`) → `billing.UserDailySeries(db, id, days)` instead of `"days": []any{}` (the SPA already asks for `?days=14`, `web/src/components/UserDetailModal.tsx:57`).

These make the feature visible without new endpoints. Keep them out of the first commit if a smaller diff is preferred.

## 5. C5 — live snapshot

### 5.1 Collector ticker

New `internal/panel/live_worker.go` (same goroutine pattern), started from `Mount`:

- ticker at `telemetry.PollSeconds()` (`internal/telemetry/handler.go:468-476`, env `OVMANAGER_LIVE_POLL_SECONDS`, default 30) — today this function has **zero callers**; wiring it retires the dead code and makes the documented env var real;
- calls `telemetry.CollectLiveSnapshot(h.Svc.DB())`;
- boot delay 15s.

Single caller invariant: `graceUntil` (`internal/telemetry/handler.go:459-464`) and the package-level alert maps have no lock. Keep the collector on exactly one goroutine and assert that in a comment; do **not** also call it from an HTTP handler or from the SSE subscribe path.

### 5.2 Idle cadence

The existing gate (`handler.go:480`) skips only when there are no subscribers *and* the snapshot is fresh, which would poll every 30s forever on an idle panel. Replace with an explicit window:

```
window := PollSeconds()
if !DefaultBus.HasSubscribers() { window = idlePollSeconds() }   // default 300
if LastPollTS() != 0 && now-LastPollTS() < window { skip }
```

That is what `README.md:175` claims (its "every 10 seconds" figure is wrong too — fix the sentence to match the real defaults).

### 5.3 Parallel polling, unchanged online semantics

The collector's per-node loop (`handler.go:523-546`) is sequential with `ProbeTimeout` per node; N dead nodes serialize into minutes. Switch to `node.GatherNodes(calls, node.RequestFanoutDeadline)`, preserving today's semantics exactly:

- **Online criterion stays "the node answered"**: `len(data) == 0` ⇒ offline (`handler.go:529`). A reachable node with zero live sessions is online with zero connections. Do not redefine this as "empty `live_sessions` ⇒ offline", which would mark every idle node offline and empty the subscription page.
- **CN → username mapping stays as it is**: `common_name` is the panel user id in decimal (OVNode `users.py:30-36`), resolved through the `id → name` map built from `SELECT id, name FROM users` (`handler.go:501-510`, applied at `:539`), with the raw CN kept when unmapped. `billing.ExtractUsername` is *not* a substitute — it strips a node-name suffix, which numeric ids never carry. Keep it only as the secondary path for name-shaped CNs (legacy/foreign clients), so a node whose sessions carry usernames still maps correctly.
- Node timeout = `ProbeTimeout(n)`; a node that exceeds the deadline is `offline` for this tick (grace then applies).

### 5.4 Consumers

- `userRow.live()` (`internal/users/handler.go:114-119`) → `active_connections` from `telemetry.Connections()[name]`, `online` = count > 0. Delete the `ponytail:` comment; the field becomes real.
- Subscription links and the health checklist need no code change once the snapshot is fed.
- UI needs no change: `LiveContext.tsx` treats SSE frames purely as invalidation signals and already has an 8s REST fallback, so correct REST data surfaces immediately.

### 5.5 Snapshot bookkeeping (small)

- `updateSnapshot` trims only the `nodes` map to `SnapshotMaxNodes`; `connections` is unbounded. Trim both by the same rule (or state the ceiling in a comment if intentional).
- DB errors inside the collector currently produce a silent empty snapshot; at minimum log a line with the tick's node/user counts so an empty result is diagnosable.

## 6. Prerequisite: the two process-killing races

Adding two always-on tickers increases the overlap probability of two known unrecoverable failures. Do these **before or in the same change**:

1. `NodeClient` stamps `c.Headers()["X-Panel-ID"]` onto a shared cached client (`internal/node/connection.go:57-62`), while `roundtrip` ranges `c.headers` (`internal/node/client.go:335`). Concurrent map iteration + write is a runtime fatal no `recover` can catch. Fix: carry the panel id in `reqOpts` per request (the `rawHeader` path already exists at `client.go:338`) and stop mutating shared client state.
2. `nodeState` / `lastDownAlert` / `alertedDownSet` (`internal/telemetry/handler.go:759-763`) are written by `CollectMetrics` (`handler.go:371`), which is reachable concurrently from the HTTP `POST /metrics/collect` handler (`handler.go:215`) and the worker tick (`internal/panel/telegram.go:24`). Separately, `checkState` (`internal/panel/health.go:33`) is written from the health handler path via `recordCheckTransition` (`health.go:346-348`), so two concurrent overview requests race the same map. Both are fatal-class; fix with one mutex-guarded struct per package (or by making those writes single-caller).

Both are small, self-contained, and independently testable with `go test -race`.

## 7. Verification

Go:

- `go test ./... -race` — the gate CI already runs; must stay green.
- `go vet ./...` clean (extend the Makefile lint target to `./...`, which currently skips `test/`).
- New tests:
  - `internal/node`: usage pass against an `httptest` node returning fixed `totals`; two nodes in one pass must both bill (guards 1.0.44); a deleted user mid-pass is skipped and other users still bill (guards 1.0.45); an OCC conflict (mutate `node_usage` between read and write) retries and still bills once, not twice; **first poll on a fresh DB seeds and bills zero**; **a NULL `used` row still bills** (guards §4.3 step 7).
  - `internal/billing`: assert `ApplyUserTraffic` + `RecordDailyBytes` inside one tx roll back together on a forced failure.
  - `internal/users`: reset sets the marker and keeps baselines; the pass after a reset seeds (delta 0) and does not re-bill a live session's bytes; reset-all keeps `push_hash`; `aggregateNodeUsage` skips reserved keys and resolves ids to names with a name fallback.
  - `internal/telemetry`: snapshot freshness window (subscribers ⇒ 30s, none ⇒ 300s), `updateSnapshot` / `applyGrace` behaviour (currently untested), collector fanout with two fake nodes where one times out, and an idle-but-reachable node staying online.
- `test/` parity: extend the `test/users_test.go:314-341` reset case (it currently pins `node_usage` collapsing to `{}` — that assertion changes under §4.6) and add the reseed/no-double-bill case.

Manual/runtime (this machine is the test VPS):

- `make build`, run the panel against a node-less DB: no crash, usage pass logs 0 nodes, snapshot tick logs 0 nodes.
- With one node: subscription page renders a link within one idle window; `/overview` shows live freshness; a user's `used` grows after traffic; `used` appears on the users list.
- Quota: set `total` below current `used`, confirm OVPN download 403 and subscription refusal within one poll interval.

## 8. My calls (check these)

1. Delta source = node `totals` (cumulative), not `sessions`.
2. Baseline keyed by **node id** (not name), value bare int64; absent key or set marker ⇒ seed with delta 0, never bill the first observation.
3. Reset = zero `used` + keep baselines/`push_hash` + set `__reseed`; next pass seeds per node. No node-side bank reset (that is why node `reset-usage` is not called).
4. `ApplyUserTraffic`/`RecordDailyBytes` gain an `execer` parameter so a per-user write is one transaction, and move to the `COALESCE(...) IS ?` guard dialect that fixes NULL `used`.
5. Usage cadence 60s via `OVM_TRAFFIC_POLL_SECONDS`; snapshot cadence 30s / 300s idle via the existing env vars; each on its own goroutine, never behind the Telegram `ready()` gate.
6. No `traffic_ledger` writes in the hot loop; ledger stays a callable audit trail.
7. No auto-kick on quota; enforcement stays at config-download time.
8. Collector stays single-goroutine; the two map races (§6) are prerequisites, not optional.
9. C5 keeps the existing "node answered ⇒ online" rule and the numeric-CN → `id → name` mapping; `topTraffic` and the per-day series get wired in the same change.

## 9. Open knobs (safe defaults chosen; easy to change)

- Cadence values, and whether they should become panel settings (DB) instead of env vars.
- Whether quota enforcement should additionally kick live sessions.
- Whether the ledger should be written per tick (currently deferred).
- Whether `internal/telemetry.CollectMetrics`' bot gate should also be lifted (separate follow-up: it leaves dashboards empty on bot-less installs).
