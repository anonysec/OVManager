# Diet OVM Plan (tests + LOW_RESOURCE mode)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fewer tests (delete-only, no coverage loss) + LOW_RESOURCE mode for 1vCPU/1GB boxes.

**Architecture:** Deletions first (safe), then one `perf.low_resource` settings_kv flag (default false) that stretches intervals + trims memory; defaults unchanged when off.

**Tech Stack:** pytest-xdist, APScheduler triggers, settings_kv (exists), get_setting KV-first (exists).

**Spec:** exp-4 suite profile + exp-5 runtime profile (file:line refs inline). Gate 0 = user picked "All".

## Global Constraints

- filterwarnings = error; TDD for behavior changes (deletions need no new tests, but suite must stay green); no new deps; house rules.
- Never delete a test that is the sole cover for a behavior (each deletion names surviving cover).
- LOW_RESOURCE off = byte-identical behavior (all existing tests run with flag off AND on where cheap).

## Review Focus

- Deleted test was sole cover → suite still green but behavior unpinned; each task names surviving cover file:line.
- Low mode on: expiry/enforce still fires (inline after K3, 5min cadence preserved).
- Idle snapshot consumers (users.py:147, sub.py:199, health.py:139) never serve >5min-stale data after freshness fix.
- Bot disabled+low mode: no process spawned, no watchdog; enabled path untouched.
- prune/metrics/debounce still run (slower), never dropped.

---

### Task 1: Delete redundant tests (10 cuts)

**Files:** delete `tests/test_makefile_lint.py`; edit test_manager_sh.py (drop :239 help, :258 unknown-opt, :487 set-e scan); fold test_smoke.py 5 asserts into test_health_endpoints/test_access_control/test_app; merge test_installer_errors.py DIE_CASES into test_installer_sh.py then delete file; merge test_tls_config.py 3 tests into test_tls_source.py then delete; halve test_public_ip_selection.py manager.sh params (keep install.sh 6); drop node-parity tests in test_ui_output.py; fold test_version_parity.py:50-62 to `test_pyproject_matches` only.

**Interfaces:** none (deletions).

- [ ] Step 1: Delete/merge per list; for each, record surviving cover (file:line) in commit message body.
- [ ] Step 2: Run full suite `pytest tests/ -q -n auto` → PASS, count dropped vs baseline 1031.
- [ ] Step 3: `make lint-backend` PASS.
- [ ] Step 4: Commit `git commit -m "test: drop redundant suite coverage (covers survive at ...)"`.

### Task 2: CI dedupe (backend)

**Files:** `.github/workflows/ci.yml` (drop ad-hoc `httpx` from pip install line; keep httpx2 from lockfile), `release.yml` (drop duplicate backend test job, rely on ci gate).

**Interfaces:** none.

- [ ] Step 1: Edit both files.
- [ ] Step 2: Validate YAML (`python -c yaml.safe_load`), grep that backend test runs exactly once per event outside release build.
- [ ] Step 3: Commit `git commit -m "ci: drop duplicate installs and test job"`.

### Task 3: LOW_RESOURCE flag + interval stretch

**Files:** `backend/worker.py` (read `perf.low_resource` at startup; triggers: metrics 5→15min, debounce 30→60s, reschedule `*`→`*/15`, drop enforce 10min cron keeping inline), `backend/operations/observability/live.py` (POLL 10→30s via env/KV), `backend/db/engine.py` (cache_size -32768→-8192 when low), `backend/bot_supervisor.py` (skip spawn+watchdog when telegram disabled AND low mode).

**Interfaces:** consumes get_setting KV-first (exists); produces identical behavior when flag off.

- [ ] Step 1: Failing tests — flag on → assert trigger values/intervals, cache pragma, no bot spawn; flag off → defaults unchanged.
- [ ] Step 2: Run → FAIL. Step 3: Implement. Step 4: task tests + worker/scheduler/bot suites PASS + full suite PASS twice (flag off, flag on).
- [ ] Step 5: Commit `git commit -m "feat: LOW_RESOURCE mode for small boxes"`.

### Task 4: Active-nodes-only polls + idle freshness fix

**Files:** `daily.py:312`, `daily.py:193`, `metrics.py:96` (get_all_nodes→get_active_nodes); `live.py:206` + consumers `routers/users.py:147`, `sub.py:199`, `health.py:139` (freshness check: stale >300s → treat as unknown, never serve frozen counts).

**Interfaces:** consumes get_active_nodes (verify exists, else add narrow helper with test).

- [ ] Step 1: Failing tests — decommissioned node adds zero stall time (mock 30s timeout, assert tick fast); snapshot older than 300s served as unknown.
- [ ] Step 2: Run → FAIL. Step 3: Implement. Step 4: billing/metrics/live suites + full suite PASS.
- [ ] Step 5: Commit `git commit -m "perf: skip dead nodes, fix idle snapshot staleness"`.
