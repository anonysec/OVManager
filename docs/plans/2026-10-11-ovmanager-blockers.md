# OVManager Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 🔴 blockers from 2026-10-11 senior review without behavior change beyond bounding memory and checking shell.

**Architecture:** Three isolated tasks with own tests; no shared interfaces. Makefile fix is shell-only, limiter caps are in-memory dict guards, billing fix moves commit ownership to caller.

**Tech Stack:** Python 3.12 FastAPI + SQLAlchemy 2, bash, ruff 0.16.5, pytest + xdist.

**Spec:** Senior review 2026-10-11 (ora-1) + verification fix-1. Exact values inline; no external spec file.

## Global Constraints

- `filterwarnings = error` — no new warnings.
- No code comments unless non-obvious tradeoff (house rule).
- Prefix-agnostic: no hardcoded `/api`.
- `SessionLocal expire_on_commit=False` — refresh after Core UPDATE when reusing object.
- Shell: `set -euo pipefail`, quote expansions, no `eval` on external input.
- Canonical lint is `make lint-backend` (CI calls it; do not copy targets).

## Review Focus

- Spray from 20k distinct IPs in one window → dict stays ≤ cap, oldest evicted, legit IP unaffected.
- `_SUB_WINDOW` boundary hit at exactly 60s → 31st request in window 429s, first-after-window passes.
- `prune_daily` caller batching two deletes then rolling back → both rolled back (no inner commit).
- `bash -n` on broken manager.sh → lint fails even when install.sh clean.
- Login purge skipped for 599s under load → inserts still bounded.

---

### Task 1: Makefile shell check checks both installers

**Files:**
- Modify: `/root/workspace/OVManager/Makefile:45-49`
- Test: `tests/test_makefile_lint.py` (new, asserts Makefile text)

**Interfaces:**
- Consumes: none
- Produces: `lint-backend` fails if either script has syntax error

- [ ] **Step 1: Write failing test**

```python
def test_makefile_checks_both_scripts():
    text = open("Makefile").read()
    assert "bash -n install.sh && bash -n manager.sh" in text
    assert "scripts/lib/*.sh" not in text.split("lint-backend")[1].split("\n\n")[0]
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd /root/workspace/OVManager && .venv/bin/python -m pytest tests/test_makefile_lint.py -q -p no:cacheprovider`
Expected: FAIL (`bash -n install.sh manager.sh` still present)

- [ ] **Step 3: Implement in `Makefile:48`**

Replace line 48 with `bash -n install.sh && bash -n manager.sh`. Delete `scripts/lib/*.sh` from that line (dir absent; `scripts/` holds README/compose/docs/export_openapi.py only).

- [ ] **Step 4: Verify PASS**

Run: `cd /root/workspace/OVManager && .venv/bin/python -m pytest tests/test_makefile_lint.py -q -p no:cacheprovider` → PASS; then `bash -n install.sh && bash -n manager.sh && echo OK` → OK; then `make lint-backend` → PASS.

- [ ] **Step 5: Commit**

```bash
git add Makefile tests/test_makefile_lint.py && git commit -m "fix: lint both shell scripts"
```

### Task 2: Bound in-memory rate-limiter dicts

**Files:**
- Modify: `/root/workspace/OVManager/backend/auth/auth.py:26-57` (`_login_attempts`, `_put_bucket`, `_purge_stale_attempts`)
- Modify: `/root/workspace/OVManager/backend/routers/sub.py:19-38` (`_SUB_ATTEMPTS`, `_sub_purge_stale`, `_sub_rate_limited`)
- Test: `tests/test_ratelimit_bounds.py` (new)

**Interfaces:**
- Consumes: none
- Produces: dicts never exceed cap; behavior under cap unchanged

- [ ] **Step 1: Write failing tests**

```python
def test_login_buckets_bounded(monkeypatch):
    import backend.auth.auth as a
    monkeypatch.setattr(a, "_CLEANUP_INTERVAL", 10**9)
    for i in range(11000):
        a._put_bucket(f"k{i}", [0.0])
        if hasattr(a, "_enforce_bucket_cap"):
            a._enforce_bucket_cap()
    assert len(a._login_attempts) <= 10000

def test_sub_buckets_bounded():
    import backend.routers.sub as s
    now = 1000.0
    for i in range(11000):
        s._SUB_ATTEMPTS[f"k{i}"] = [now]
    s._sub_purge_stale(now + 0.1)
    # purge window not elapsed so still large -> cap enforcement needed on insert path
    assert len(s._SUB_ATTEMPTS) > 10000  # documents current gap; after fix assert <= 10000
```

Second assert starts red by design; rewrite to `<= 10000` as fix lands (keep one commit, update test before implement).

- [ ] **Step 2: Run, expect FAIL**

Run: `cd /root/workspace/OVManager && .venv/bin/python -m pytest tests/test_ratelimit_bounds.py -q -p no:cacheprovider`
Expected: FAIL on size asserts.

- [ ] **Step 3: Implement caps**

`auth.py`: add `_MAX_BUCKETS = 10000  # ponytail: in-memory only, Redis when multi-instance`. In `_put_bucket`, after insert, if `len > _MAX_BUCKETS`, evict entries with stalest `times[-1]` first (single pass, no new deps). Same guard at end of `_purge_stale_attempts`.
`sub.py`: add `_SUB_MAX_BUCKETS = 10000`; in `_sub_rate_limited` after `_SUB_ATTEMPTS[key] = hits`, enforce same eviction. Keep `_SUB_MAX=30`, `_SUB_WINDOW=60` unchanged. `owner_claim.py:118` already caps at 1000 — leave untouched.

- [ ] **Step 4: Verify PASS**

Run: `cd /root/workspace/OVManager && .venv/bin/python -m pytest tests/test_ratelimit_bounds.py tests/test_cli.py -q -p no:cacheprovider` → PASS. Then `.venv/bin/ruff check backend tests && .venv/bin/ruff format --check backend tests` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/auth/auth.py backend/routers/sub.py tests/test_ratelimit_bounds.py && git commit -m "fix: bound rate-limiter buckets"
```

### Task 3: `prune_daily` must not commit internally

**Files:**
- Modify: `/root/workspace/OVManager/backend/operations/billing/usage.py:79-86`
- Modify: callers found via `grep -rn prune_daily backend cli tests` (update each to commit)
- Test: extend `tests/test_billing_*.py` or new `tests/test_prune_daily_txn.py`

**Interfaces:**
- Consumes: caller-owned transaction
- Produces: `prune_daily(db, keep_days) -> int` with no commit

- [ ] **Step 1: Write failing test**

```python
def test_prune_daily_no_inner_commit(db, monkeypatch):
    import backend.operations.billing.usage as u
    committed = []
    monkeypatch.setattr(db, "commit", lambda: committed.append(1))
    u.prune_daily(db, keep_days=90)
    assert committed == []
```

(Use repo's existing `db` fixture name; check conftest first — adapt name, keep assertion.)

- [ ] **Step 2: Run, expect FAIL** (commit called once)

Run: `cd /root/workspace/OVManager && .venv/bin/python -m pytest tests/test_prune_daily_txn.py -q -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

Delete `db.commit()` at `usage.py:85`. At each caller site, add explicit `db.commit()` after call (same order, no logic change).

- [ ] **Step 4: Verify PASS**

Run: task test + full billing subset `pytest tests/ -q -p no:cacheprovider -k billing` → PASS. Ruff check/format on touched files → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/operations/billing/usage.py tests/test_prune_daily_txn.py $(git diff --name-only | grep -v usage.py) && git commit -m "fix: prune_daily leaves commit to caller"
```
