# Lightweight cuts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Single-admin OpenVPN panel: drop multi-admin, single-source i18n lists, .db-only backups, graphify local-only.

**Architecture:** Delete management surface, keep one owner credential; share lang lists not strings; copy .db not bundle; delete untracked graph dirs. Updater + rollback stays.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (WAL), React 19 + Vite + i18next, shell install/manager.

**Spec:** This plan IS the spec (user-approved 4 cuts, 2026-10-08 chat). Updater/rollback explicitly kept. install.sh = install-only, manager.sh = post-install manage; both stay, no merge/drop.

**Explicitly kept (user 2026-10-08):** billing/limits (abuse guard), worker (enforces billing), migration runner (future DB/feature changes), doctor (user-friendly vs raw API), geo visuals.

## Global Constraints

- `ruff check backend cli main.py tests scripts/bench` + `ruff format --check` must pass.
- `pytest tests/ -q` (filterwarnings=error) must pass; backup/perms tasks also `sudo -u ovmanager` run.
- Frontend: `npm run verify` (build + tokens + i18n + rtl + eslint + types + vitest).
- Never call `i18n.changeLanguage` directly; use `loadLanguage()`.
- Only `tokens.css` declares `:root`; logical CSS only.
- No new comments unless asked.
- Panel stays prefix-agnostic; node calls via `node_client(node)`.

## Review Focus

- Old admin login with second admin still works (must 401/403 after cut).
- fa still flips RTL with translated strings (not English + RTL).
- Restored .db opens + `quick_check` ok after WAL writer active.
- `git ls-files | grep graphify` stays empty; CI graph jobs unaffected.
- Updater rollback path still finds pre-update backup (format change must not break it).

---

### Task 1: Single-admin (remove multi-admin surface, keep owner login)

**Files:**
- Modify: `backend/db/models.py:28-42` (Admin: drop `username_prefix,disabled,default_days,default_traffic_gb,default_max_users`; keep username/password/is_owner/telegram_id)
- Modify: `backend/db/models.py:23` (`User.owner` → nullable, then drop after backfill; single migration)
- Modify: `backend/auth/authz.py:9-38` (`require_owner` stays, `require_user_access`/`owned_by` → pass-through single tenant)
- Delete: `backend/routers/admins.py` (whole file) + unregister router in `backend/app.py`
- Modify: `backend/routers/users.py:63-85,98,188-190,237-238,343,374,414-415,526` (drop prefix source + owner branching; `owner=single`)
- Modify: `backend/db/crud/users.py:86-133,36-62,282-293` (`effective_user_defaults` → `settings.default_*` only)
- Delete: `backend/db/crud/admins.py:12-57` except `get_admin_by_username` (owner login) + `get_admin_by_telegram_id` (delete second, keep owner check)
- Modify: `backend/auth/auth.py:97-136,300-302` (auth against single owner row; role always `owner`)
- Modify: `backend/routers/owner_claim.py:74-85,152-274` (claim checks single row, no rename cascade)
- Modify: `cli/password.py:110-154` (reset single owner row)
- Modify: `backend/bot/identity.py:19-131` (owner via `settings.owner_telegram_id` only; drop `panel.get_admins()` scan)
- Modify: `backend/bot/handlers/home.py:16,26,72`, `settings.py:22`, `edit.py:42,136`, `setup.py:40`, `users.py:91`, `create.py:54` (drop `role != owner` gates)
- Modify: `backend/bot/api.py:147,209-210` (drop `/admin/` pulls)
- Modify: `backend/db/migrations/seeds.py:58-150`, `steps.py:127-136,296-315,345-362` (new migration drops columns; old steps no-op)
- Delete: `frontend/src/pages/Admins.tsx`, nav in `Sidebar.tsx:107`, `CommandPalette.tsx:15`, keys `en.json:263-289` (+fa/ru/cn same)
- Test: `tests/test_admin_lifecycle.py` (delete file), update `test_access_control.py:50,259-281`, `test_authz_ownership.py:29`, `test_partf_backend.py:354-430`, `conftest.py:131,214-223`

**Interfaces:**
- Consumes: `settings.default_days/traffic_gb` (single source).
- Produces: `get_current_user() -> owner only`; `effective_user_defaults() -> settings only`.

- [ ] **Step 1: Write failing test** `tests/test_single_admin.py`: create second admin → expect 404/403; list users as owner → all users (no scoping).
- [ ] **Step 2: Run it** ` .venv/bin/python -m pytest tests/test_single_admin.py -q` Expected: FAIL (second admin creatable).
- [ ] **Step 3: Implement** per Files above; migration backfills `User.owner='admin'` then drops column in same release.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_single_admin.py tests/test_owner_claim.py tests/test_authz_ownership.py -q` Expected: PASS. Then full `.venv/bin/python -m pytest tests/ -q`.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: single-admin only"`

### Task 2: i18n single-source lists (keep two trees)

**Files:**
- Modify: `frontend/src/i18n.js:9-35` (export `SUPPORTED_LANGS`, `isRTL(lng)`)
- Modify: `frontend/src/pages/settings/AppearanceSection.tsx:33-41` (map over `SUPPORTED_LANGS`)
- Modify: `frontend/src/pages/DashboardLayout.tsx:132-138,397-414` (delete dir/lang effect; map buttons over `SUPPORTED_LANGS`)
- Modify: `frontend/src/utils/time.js:10` (use shared `isRTL`)
- Modify: `frontend/scripts/check-i18n.mjs:24` (budget 13 → 0)
- Create: `frontend/src/i18n.locales.test.ts` (assert bot `LOCALES` == frontend lang files)
- Test: `frontend/src/i18n.lazy-locale.test.ts` (keep grep guard passing)

**Interfaces:**
- Consumes: `src/lang/*.json` filenames.
- Produces: `SUPPORTED_LANGS: string[]`, `isRTL(lng: string): boolean`.

- [ ] **Step 1: Write failing test** assert `AppearanceSection` renders from `SUPPORTED_LANGS` length (4); DashboardLayout has no `localStorage['ovmanager-lang']` write.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/i18n.locales.test.ts` Expected: FAIL.
- [ ] **Step 3: Implement** (a)+(b)+(c) from recon; do NOT merge JSON trees (overlap 2 keys: `error`, `unlimited`).
- [ ] **Step 4: Run** `node scripts/check-i18n.mjs && npm run verify` Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "refactor: single-source i18n lists"`

### Task 3: .db-only backups (keep updater + rollback)

**Files:**
- Modify: `backend/routers/maintenance.py:86` (`create_bundle` → `shutil.copy2(snapshot, BACKUP_DIR/f"ovmanager-{label}-{stamp}.db")` + chmod 0600; prune glob `ovmanager-{label}-*.*`)
- Modify: `backend/routers/maintenance.py:340-347,417-431` (safety copy plain `.db`; collapse `_restore_artifact` to `:431` path)
- Modify: `backend/routers/maintenance.py:184` (list: skip `verify_bundle` block; tag `db`)
- Keep: `_sqlite_backup`, WAL checkpoint `:77`, sidecar removal `:259-268`, `_atomic_db_restore` chown gates `:333-359,388-392`, prune loop, offsite/telegram signatures
- Modify: `install.sh:1530-1598` (pre-update writer emits `.db`; prune keep 10)
- Test: `tests/test_maintenance_backup.py:70-71,137` (gzip magic → sqlite magic `SQLite format 3`; glob `.db`), retire `tests/test_backup_bundle.py` to legacy

**Interfaces:**
- Consumes: live `panel.db` (WAL).
- Produces: `BACKUP_DIR/ovmanager-{label}-{stamp}.db` (0600), `quick_check` clean.

- [ ] **Step 1: Write failing test** roundtrip backup→restore asserts filename endswith `.db` + `hex == SQLite format 3`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_maintenance_backup.py -q` Expected: FAIL (makes `.ovmbak`).
- [ ] **Step 3: Implement** writer swap only; prove test bites: revert fix in /tmp copy → red, restore → green.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_maintenance_backup.py tests/test_restore_transaction.py tests/test_cli_backup.py -q` + `sudo -u ovmanager env HOME=/root .venv/bin/python -m pytest tests/test_maintenance_backup.py tests/test_restore_transaction.py -q -p no:cacheprovider` Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "refactor: db-only backups"`

### Task 4: Graphify local-only (already ignored; delete disk + 1 tracked line)

**Files:**
- Delete (disk only): `graphify-out/` (58M) + `backend/graphify-out/` (3.9M) + `frontend/src/graphify-out/` (60K) in OVManager; `graphify-out/` (12M) in OVNode
- Modify: `OVManager/.gitattributes:1` (delete file; sole line `graphify-out/graph.json merge=graphify`)
- Keep untouched: `.gitignore` (`graphify-out/` already covers nested), `.github/workflows/graph-rebuild.yml`, `graph-staleness.yml`, `.github/scripts/graph_staleness.py` (both repos assert untracked)

**Interfaces:**
- Produces: `git ls-files | grep -i graphify` → empty; `git status --ignored` shows `!! graphify-out/`.

- [ ] **Step 1: Verify tracked empty** `git ls-files -- '*/graphify-out/*' 'graphify-out/*'` Expected: empty (already true).
- [ ] **Step 2: Delete disk dirs** `rm -rf` the 4 paths + `git rm .gitattributes` (OVManager only).
- [ ] **Step 3: Verify** `git ls-files | grep -i graphify` → empty; `git check-ignore graphify-out backend/graphify-out frontend/src/graphify-out` → all ignored.
- [ ] **Step 4: Commit** `git commit -m "chore: graphify local-only"`

### Task 5: TLS 3 options (self-signed / LE-ACME / custom path), DB default + .env force

**Files (options already exist — trim + wire DB/env, no new flows):**
- Keep: `backend/routers/tls.py:/upload :499` (custom), `/self-signed :617` (self), `/renew :667` (LE/ACME), `/status :405`, `/settings :109`, `/restart :895` (runtime apply, e.g. URLPATH change), `_detect_primary_ip :546-578` as fallback only (prefers public IPv4, skips docker/private; behind NAT it can only see private — installer `public_ip()` via ipify/ifconfig is truth). Order: DB `TLS_DOMAIN`/stored public IP → installer value → `_detect_primary_ip()` → 127.0.0.1. Delete only `_port_80_busy` :645-653 (rely on acme fail).
- DB already has `models.py:113 ssl_cert_file` + `:117 cert_method=selfsigned`; add `ssl_key_file` + `custom path` support if missing (custom = user-provided cert+key path)
- Modify: `backend/routers/setting.py` + `backend/db/models.py:110-112` (settings columns: `tls_method self|acme|custom`, `tls_certfile`, `tls_keyfile`; DB is default source)
- Modify: `main.py:81-102` (start: if `SSL_KEYFILE/SSL_CERTFILE` env set (uncommented) → force env paths; else read DB settings; fail if unreadable; uvicorn `ssl_keyfile/ssl_certfile` only, no HTTP listener; port 80 only during `/tls/renew`)
- Modify: `.env.example:44-46` (already commented `# SSL_KEYFILE/# SSL_CERTFILE`; extend comment: uncomment to force over DB)
- Modify: `install.sh:1337-1371,1183-1335` (bootstrap self-signed; keep `tls.sh` lib), `manager.sh:1920-1970` (`do_https()` keeps restart ownership)
- Keep: `middlewares.py:90-91` HSTS, `app.py:279-281` SecurityHeaders
- Test: keep `tests/test_tls_perms.py`; delete `tests/test_tls_primary_ip.py`; keep `tests/test_tls_reuse.py`; add `tests/test_tls_source.py` (DB default vs .env force)

**Rule (new-server safe):** serving truth = files via `tls_paths` (.env declared or `/etc/ovmanager/tls` default), never DB paths. DB `ssl_*`/`cert_method` = record for UI only. Boot: if key/cert missing at serving paths → generate self-signed there, update DB record, log, stay HTTPS. Never fall back to HTTP. Restored DB on new server without files → fresh self-signed, operator re-uploads custom/renews LE after.

- [ ] **Step 1: Write failing test** `test_tls_source.py`: set DB custom + env empty → source db; set env paths → source env (force).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_tls_source.py -q` Expected: FAIL (no source field).
- [ ] **Step 3: Implement** DB-default + env-override resolver + trim deletes above.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_tls_source.py tests/test_tls_perms.py tests/test_tls_reuse.py -q` Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: tls 3-option db plus env force"`
