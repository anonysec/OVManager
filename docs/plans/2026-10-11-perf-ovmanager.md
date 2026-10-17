# Perf OVM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v25 schema (traffic_ledger + settings_kv) plus 9 borrowables, panel-side, zero-loss cursor accounting.

**Architecture:** Additive migration first, then readers/writers move one job at a time; ledger and KV are the only new tables ever needed (ledger grain per-poll aggregate per user per node; knobs live in KV from here on).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, SQLite WAL, APScheduler, pytest-xdist.

**Spec:** `.slim/deepwork/perf-opt/schema-design.md` as amended by Gate 0 (2 tables not 4; cursor not drain; node_presence dropped; restart flag lives at settings_kv `sync.restart_debounce`). Defaults assumed unopposed: per-poll grain, 30s debounce, snapshot cap 50, one-time v25 backfill.

## Global Constraints

- filterwarnings = error; NullPool; single worker; no new deps.
- Migrations: explicit STEPS entry required (no auto-reconcile on stamped DBs); additive only; must apply cleanly atop 17-24 path (checked-in db stamped 16).
- Cursor + ledger insert in one txn (exactly-once); expire_on_commit=False — refresh after Core writes.
- No code comments unless non-obvious tradeoff. Canonical lint `make lint-backend`.

## Review Focus

- Panel crash between node read and commit → redeliver same cumulative next poll, ledger has no dup (UNIQUE user,ts,kind,node), cursor unmoved.
- Missed polls for hours → next poll yields one large delta, single txn, no overflow (INTEGER).
- 1000 users × 5 nodes per tick → one txn, rows sorted by (user_id, node_id).
- Concurrent ticks → second tick single-flights away, never piles up.
- v25 on db stamped 16 → migrates 17-25 green, verify_schema clean, backfill row counts match user_traffic_daily.

---

### Task 1: v25 migration (ledger + kv + backfill)

**Files:**
- Modify: `backend/db/migrations/constants.py` (_EXTRA_DDL + SCHEMA_VERSION 25), `backend/db/migrations/steps.py` (v25 step)
- Test: `tests/test_traffic_ledger_migration.py`

**Interfaces:**
- Consumes: _create_extra_tables pattern (schema.py:128-140)
- Produces: traffic_ledger(user_id, ts, node_id, kind, delta_bytes, meta_json DEFAULT '{}', UNIQUE(user_id,ts,kind,node_id)), settings_kv(key PK, value, updated_at)

- [ ] **Step 1: Write failing test** — migrate fixture db, assert tables exist, backfill counts equal user_traffic_daily rows, UNIQUE enforced on dup insert, version stamped 25.
- [ ] **Step 2: Run, expect FAIL** (`pytest tests/test_traffic_ledger_migration.py -q -p no:cacheprovider` — no such tables).
- [ ] **Step 3: Implement** — DDL in _EXTRA_DDL, v25 step creates + backfills (day→delta, kind='backfill', node_id NULL) + stamps. Keep user_traffic_daily writes for now.
- [ ] **Step 4: Verify PASS** — task test + `verify_schema` clean + full `pytest tests/test_migrations*.py -q` PASS.
- [ ] **Step 5: Commit** — `git add backend/db/migrations tests/test_traffic_ledger_migration.py && git commit -m "feat: v25 traffic ledger and settings kv"`

### Task 2: Pragma hardening

**Files:**
- Modify: `backend/db/engine.py:16-30`
- Test: `tests/test_pragma_profile.py`

**Interfaces:**
- Consumes: existing connect hook
- Produces: same hook plus temp_store=memory, cache_size, mmap_size (keep WAL/NORMAL/timeout=30/FK)

- [ ] **Step 1: Write failing test** — fresh DB, assert pragma values via SELECT.
- [ ] **Step 2: Run, expect FAIL** (new pragmas absent).
- [ ] **Step 3: Implement** — add PRAGMAs to connect hook. Do NOT lower busy_timeout.
- [ ] **Step 4: Verify PASS** — task test + `make lint-backend` PASS.
- [ ] **Step 5: Commit** — `git commit -m "perf: harden sqlite pragma profile"`

### Task 3: SettingsCache + refresh

**Files:**
- Modify: `backend/config.py` (SettingsCache), `backend/routers/setting.py` (invalidate on write), `backend/db/crud/settings.py` (read-through)
- Test: `tests/test_settings_cache.py`

**Interfaces:**
- Consumes: get_settings(db) row-1 SELECT
- Produces: `get_cached_settings()`, `refresh_settings()`; URLPATH cache untouched

- [ ] **Step 1: Write failing test** — two reads → one SELECT (count via event listener); write → refresh → new value visible.
- [ ] **Step 2: Run, expect FAIL** (two SELECTs).
- [ ] **Step 3: Implement** — process-local dict + refresh on all setting-mutating routes (grep get_settings callers; wire every writer).
- [ ] **Step 4: Verify PASS** — task test + touched router tests PASS + ruff PASS.
- [ ] **Step 5: Commit** — `git commit -m "perf: cache settings with explicit refresh"`

### Task 4: Single-flight scheduler jobs

**Files:**
- Modify: `backend/scheduler.py`, `backend/worker.py` (usage/collector/prune/metrics jobs)
- Test: `tests/test_scheduler_single_flight.py`

**Interfaces:**
- Consumes: existing CronTriggers (5min poll, 10min enforce, 6h prune)
- Produces: max_instances=1, coalesce=True, module _running guards on the four jobs; intervals unchanged

- [ ] **Step 1: Write failing test** — fire same job twice concurrently, assert body ran once.
- [ ] **Step 2: Run, expect FAIL** (runs twice).
- [ ] **Step 3: Implement** — guards + scheduler kwargs.
- [ ] **Step 4: Verify PASS** — task test + `pytest tests/ -q -k scheduler -p no:cacheprovider` PASS.
- [ ] **Step 5: Commit** — `git commit -m "perf: single-flight scheduler jobs"`

### Task 5: Presence grace + live gating + caps

**Files:**
- Modify: `backend/operations/observability/live.py` (grace window, watcher gate, snapshot cap), `backend/routers/telemetry.py` (cap passthrough)
- Test: `tests/test_presence_grace.py`, extend live tests

**Interfaces:**
- Consumes: LiveSnapshot, LiveBus, collect_live_snapshot (10s, 300s idle skip stays)
- Produces: grace=20s down→grace→down; no-subscriber → skip node probes; snapshot cap from settings_kv `telemetry.snapshot_max_nodes` default 50

- [ ] **Step 1: Write failing tests** — down node visible 20s then drops; zero subscribers → zero probe calls (monkeypatch probe); 60 nodes → snapshot capped at 50.
- [ ] **Step 2: Run, expect FAIL** (all three).
- [ ] **Step 3: Implement** — grace timestamps in snapshot; `bus.has_subscribers()`-style gate (add counter if missing); cap slice.
- [ ] **Step 4: Verify PASS** — task tests + existing live/telemetry tests PASS.
- [ ] **Step 5: Commit** — `git commit -m "perf: presence grace window and gated live snapshots"`

### Task 6: Batched sorted upsert + prune_ledger

**Files:**
- Modify: `backend/operations/billing/daily.py` (_apply_user_traffic path), `backend/operations/billing/usage.py` (prune_ledger), callers scheduler.py:51-63 + maintenance.py:654-660
- Test: `tests/test_batched_upsert.py`, `tests/test_prune_ledger.py`

**Interfaces:**
- Consumes: traffic_ledger (Task 1), per-tick deltas map
- Produces: one txn per tick, rows sorted (user_id, node_id); prune_ledger(keep_days) no inner commit

- [ ] **Step 1: Write failing tests** — 1000-user tick asserts single commit (count) + sorted executemany order; prune deletes >90d in batches, returns count, no commit.
- [ ] **Step 2: Run, expect FAIL**.
- [ ] **Step 3: Implement** — fold per-user writes into one executemany; prune with LIMIT batches; callers commit.
- [ ] **Step 4: Verify PASS** — task tests + `-k "billing or prune or usage"` PASS.
- [ ] **Step 5: Commit** — `git commit -m "perf: batched ledger upsert and prune"`

### Task 7: Delta collection with cursor (exactly-once)

**Files:**
- Modify: `backend/operations/billing/daily.py` (collect job every 5min, existing trigger), `users.node_usage` JSON cursor `{node: cumulative}`
- Test: `tests/test_delta_collection.py`

**Interfaces:**
- Consumes: GET /sync/usage totals (cumulative per user), traffic_ledger, Task 6 writer
- Produces: delta = cumulative − cursor; ledger insert + cursor update in ONE txn; panel:reset advances cursor (no node call)

- [ ] **Step 1: Write failing tests** — poll → ledger row + cursor moved; same cumulative repolled → zero rows; simulated crash before commit → redelivery inserts once; reset → cursor jumps, next delta 0.
- [ ] **Step 2: Run, expect FAIL**.
- [ ] **Step 3: Implement** — job + txn; keep writing user_traffic_daily this release (dual-write, reads unchanged).
- [ ] **Step 4: Verify PASS** — task tests + billing subset PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: cursor-based delta collection"`

### Task 8: Restart debounce flag + consumer

**Files:**
- Modify: config-push writers (grep: setting/tls/node routers writing tunnel/protocol/port/PKI), `backend/worker.py` (process_restart_debounce every 30s), settings_kv key `sync.restart_debounce`
- Test: `tests/test_restart_debounce.py`

**Interfaces:**
- Consumes: settings_kv (Task 1), fanout restart path
- Produces: structural edits set flag {flag,reason,updated_at}; consumer fans out, clears on all-success, retries capped 5m; startup force-retries flag older than 5min

- [ ] **Step 1: Write failing tests** — N edits → single flag; consumer success clears; partial failure keeps flag; stale flag retried at startup.
- [ ] **Step 2: Run, expect FAIL**.
- [ ] **Step 3: Implement** — writer helper + consumer + startup check.
- [ ] **Step 4: Verify PASS** — task tests + worker tests PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: debounced node restarts"`

### Task 9: Hash-diff push + batched fanout

**Files:**
- Modify: `backend/node/sync.py` (sync_all_user_limits), `backend/node/fanout.py` (chunking)
- Test: `tests/test_hash_diff_push.py`

**Interfaces:**
- Consumes: pushed-credential payloads
- Produces: sha256(cert+key+ca+state) compare → skip unchanged; chunks ~100 users / <1MB from settings_kv `sync.batch_size`

- [ ] **Step 1: Write failing tests** — unchanged user → zero node calls; 5000 users → 50 chunks each <1MB.
- [ ] **Step 2: Run, expect FAIL**.
- [ ] **Step 3: Implement** — hash store (reuse node_usage JSON or small table? prefer node_usage key `push_hash`) + chunker.
- [ ] **Step 4: Verify PASS** — task tests + sync/fanout tests PASS.
- [ ] **Step 5: Commit** — `git commit -m "perf: hash-diff user push with batched fanout"`

### Task 10: Legacy compat (reads stay, KV fallback)

**Files:**
- Modify: `backend/config.py` (get_setting KV-first with settings-column fallback), graph/board routes untouched
- Test: `tests/test_settings_kv_fallback.py`

**Interfaces:**
- Consumes: settings_kv, settings row
- Produces: get_setting(key, default) — KV hit wins, else legacy column, else default

- [ ] **Step 1: Write failing test** — KV value overrides column; missing key falls back; unknown key returns default.
- [ ] **Step 2: Run, expect FAIL**.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Verify PASS** — task test + setting router tests PASS + `make lint-backend` PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: settings kv with legacy fallback"`
