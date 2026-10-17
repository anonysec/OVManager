# Plan: fix ovm update data-dir orphaning (v2.0.2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ovm update` carry an in-tree `DATA_DIR` across the tree swap so the panel keeps its database, claim key, node certs, and backups. Ship v2.0.2.

**Architecture:** Before swapping `/opt/ovmanager` → `.previous`, capture the resolved `DataDir` (from env or `.env` or default `<install>/data`). After extraction, before restart, migrate the captured data dir into the new tree if the new tree's data dir is empty/missing. Also keep `.env` (already preserved) and log the decision. No change to release-layout installs (DATA_DIR outside tree) — they're unaffected.

**Tech Stack:** Go 1.27.1, cobra, stdlib only. No new deps.

**Spec:** docs/superpowers/plans/2026-10-17-go-cutover.md Phase 6 + this fix. Decisions per senior dev: in-tree data migration is the fix; no config change required (keep install.sh --from-source semantics); no frontend changes.

## Global Constraints

- Touch only `internal/cli/update.go` (+ its test). No other files.
- No new deps.
- Preserve existing failover (db restore on failure).
- Commit per task, push, release v2.0.2, live-test.

## Review Focus

- Migration must not clobber a non-empty new data dir (release layout with its own data).
- Must not leave orphaned state if migration fails (restore previous).
- Must not double-migrate on re-run.
- Must log the decision (operator visibility).

---
### Task 1: Diagnose + test harness

**Files:**
- Modify: `internal/cli/update.go`
- Test: `goparity/update_test.go` (new)

**Interfaces:**
- Consumes: `Install` struct (Dir, DataDir, Env), `env.Load`, existing backup/stage/activate/verify helpers.
- Produces: `captureDataDir(inst)`, `migrateDataIfInTree(prevDir, newDir)` helpers, wired into `doUpdate`.

- [ ] **Step 1: Write failing test** (`goparity/update_test.go`)

```go
func TestUpdateMigratesInTreeDataDir(t *testing.T) {
    // setup: prevDir with data/ holding a marker file; newDir freshly extracted with empty data/
    // call migrateDataIfInTree(prevDir, newDir)
    // assert marker present in newDir/data/, prevDir/data/ untouched
}
func TestUpdateSkipsMigrationWhenNewDataNonEmpty(t *testing.T) { ... }
func TestUpdateSkipsMigrationWhenDataDirOutsideTree(t *testing.T) { ... }
```

- [ ] **Step 2: Run to verify they fail**

Run: `go test ./goparity/ -run 'TestUpdateMigrates|TestUpdateSkips' -v`
Expected: FAIL (helpers undefined)

- [ ] **Step 3: Implement helpers + wire into doUpdate** (capture before swap; migrate after extract; log; on failure restore previous — reuse existing failover)
- [ ] **Step 4: Run tests to verify they pass**

Run: `go test ./goparity/ -run 'TestUpdate' -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add internal/cli/update.go goparity/update_test.go
git commit -m "fix(update): carry in-tree DATA_DIR across tree swap"
```

---
### Task 2: Full verify + bump + release

**Files:**
- Modify: `internal/version/version.go` → "2.0.2"
- Modify: `install.sh` VERSION → "2.0.2"
- Modify: `CHANGELOG.md` (add 2.0.2 heading)

- [ ] **Step 1: Full verify**

Run: `go test ./... && (cd frontend && npm run verify)`
Expected: PASS

- [ ] **Step 2: Bump version** (three sites)
- [ ] **Step 3: Commit + push**

```bash
git add -A && git commit -m "chore(release): v2.0.2" && git push origin HEAD
```

- [ ] **Step 4: Publish release**

Run: `gh release create v2.0.2 --title "v2.0.2" --generate-notes`
Expected: release URL + assets workflow success

- [ ] **Step 5: Live update test on host** (run `ovm update`, expect 2.0.2, no failover, data dir preserved — verify DB size + owner-claim.key before/after)
- [ ] **Step 6: Report completion** with verbatim update output + data-dir proof
