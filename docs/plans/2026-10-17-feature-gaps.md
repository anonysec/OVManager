# Plan: Post-cutover feature gaps (x-ui comparison)

**Goal:** Close the 6 real gaps found comparing with x-ui (alireza0). Order = value/risk. Fixes are additive; no Go dep changes; frontend pro-max tokens.

**Base:** main at `3d91d4c` — binary = panel + CLI, embedded SPA (`internal/webfs`), bare-binary releases with sha256, CI green, live panel v2.0.2.

## Constraints

- No new Go deps. HTTP-only additions reuse chi patterns from `internal/panel`.
- Every endpoint admin/owner-gated like existing routers.
- `test/` parity first for each backend piece (RED→GREEN), then frontend where needed.
- Commit per task, one release at the end.

---

### Task 1: ACME + one-click TLS + auto-renew (restores #1)

**Files:** `internal/panel/tls.go` (extend), `internal/acme/` (new, tiny client), `install.sh` (offer cert at bootstrap), `web/src/pages/settings/TlsSection.tsx`, `test/tls_acme_test.go`.

- [ ] Re-add cert manage flow lost in installer slimming: in-panel settings → "Issue certificate" (user supplies domain; panel verifies port 80 reachability or uses standalone listener).
- [ ] Auto-renew worker (T-30d check, systemd-run renew via existing worker) + expiry shown on status page.
- [ ] installer: optional `--acme <domain>` flag writing cert paths into unit env (SSL_KEYFILE / SSL_CERTFILE already consumed by panel env keys).
- [ ] No new dep: use stdlib `crypto/tls` + minimal ACME via `golang.org/x/crypto/acme` (already a Go module dep of crypto/x/crypto — enumerate; if not present, vendor small/?; x/crypto already in go.mod).

### Task 2: Log viewer in panel (#4)

**Files:** `internal/panel/logs.go` (new), `web/src/pages/Logs.tsx` (new), router mount, `test/logs_test.go`.

- [ ] GET /api/logs?lines=200&unit=— streams `journalctl -u <unit> -n N -o cat --no-pager`; unit param: panel or openvpn@ — reuse CLI probes (`cli.ServiceState`) to avoid shell.
- [ ] Read-only, capped (max 500 lines), no shell injection; UI Poll/Eye icon on top-right of dashboard.
- [ ] Audit-log entry when viewed (existing audit helper).

### Task 3: Expired/depleted users sweep (#5) + kick (#6)

**Files:** `internal/users/sweep.go` (new helpers), `internal/users/handler.go` (2 endpoints), `web/src/pages/UserManagement.tsx` (filter tab + bulk action), `test/users_sweep_test.go`.

- [ ] `GET /api/users/expired` — list users with `ExpiryDate < now` or quota exceeded; `POST /api/users/purge` — bulk delete + session revoke (reuse existing revoke helper).
- [ ] `POST /api/users/:id/kick` — current revoke + propagate to nodes (existing node sync plumbing), respond with count kicked.
- [ ] Frontend: "Expired" tab with count badge + bulk delete button + confirm modal.

### Task 4: Telegram bot (ops notifications) (#2)

**Files:** `internal/notify/telegram.go` (new), `internal/panel/handlers.go` (settings endpoints), worker hook (renew worker from Task 1), `web/src/pages/settings/*Section.tsx`, `test/telegram_test.go`.

- [ ] Settings: bot token + chat id (client creds in .env), test-message button.
- [ ] Events: panel login (success/fail from login router), daily usage summary (cron time configurable), user expired/over-quota, CPU > thresh (reuse disk/cpu probe from doctor).
- [ ] Optional DB backup attach (size-capped).
- [ ] Stdlib HTTP only; no long-poll interactive bot (read-only notify channel, not a command bot — deliberate cut, note as such).

### Task 5: In-panel DB export/import (#3)

**Files:** `internal/panel/dbops.go` (new), `web/src/pages/settings/GeneralSection.tsx` (+import button), `test/dbops_test.go`.

- [ ] `GET /api/db/backup` → streams latest safety-copy SQL dump (reuse backup helper).
- [ ] `POST /api/db/restore` (multipart upload) → staging restore like update failover path; maintenance marker during swap; audit entry.
- [ ] Owner-only (not any admin).

---

## Second shelf (this wave, from post-plan review)

### Task 6: Client profile issuance — RESCOPED by investigation (corrected)

**Findings (HEAD 52c087d):** the feature already exists. UI "Get Config" → node picker → panel pulls profile from node agent (`/sync/download/ovpn/{uid}`, inline `<ca>/<cert>/<key>`), rewrites `remote` lines (panel_domain + per-other-node fallbacks), returns `.ovpn` (and `.zip` per node for owner); subscription page serves the same gated on expiry/disabled/quota. **Issuance lives node-side by design — do NOT move CA minting panel-side** (`nodes.server_ca` is the agent mTLS pin, not the OpenVPN CA). The earlier "grep ovpn = 0" was a mis-grep (searched users/ + pages, missed node/ + components).

Remaining scope (real):
- [ ] Tests first: `test/ovpn_download_test.go` — `injectRemoteLines` rewrite + `handleDownloadOVPN` gating (today: active + quota only).
- [ ] Expiry gate: `handleDownloadOVPN` must refuse when `ExpiryDate < today` (parity with the subscription page's gating).
- [ ] Wire `DeleteUserOnAllNodes` (currently dead code) into user delete so panel deletion also evicts node-side sessions/configs; document create-as-node-auto-provisioning (agent mints on first download).
- [ ] Update the db spec text in this plan: feature exists; remaining work is the 3 items above.

### Task 7: README refresh

- [ ] Drop Python badge, "installer brings its own Python runtime", `frontend/` paths (Python era docs); reflect: Go single binary, embedded SPA, bare-binary releases + sha256, docker/ghcr, Pages docs link.

### Task 8: Security headers middleware

**Files:** `internal/panel/` middleware + router mount, `test/headers_test.go`.
- [ ] CSP (strict, allow self + inline styles if needed), X-Frame-Options DENY, Referrer-Policy strict-origin-when-cross-origin, X-Content-Type-Options nosniff.
- [ ] HSTS added only when TLS active (respects the HTTP-install reality).

### Task 9: Scheduled backups

**Files:** `install.sh`, `internal/cli/backup.go` (retention flag if missing), docs.
- [ ] installer writes systemd `ovm-backup.timer` (daily, randomized delay) + `ovm-backup.service` running `ovm backup --retention 7`.
- [ ] ovm doctor's backup check should recognize the timer (verify current doctor behavior, adjust).

### Task 10: Module path + single version source

- [ ] Rename module `ovmanager-go` → `github.com/anonysec/OVManager` (one-time sed over imports; keep same layout; go.sum regenerated).
- [ ] Single version source: `internal/version/version.go` stays THE file. Release bump only touches it + CHANGELOG; `make version` regenerates `web/src/version.ts` (and package.json "version" field) from it before `npm run build`; `ovm`/panel/`About` + UI footer all read it. Docs mention dropped `pyproject.toml` reads in workflows confirmed gone.

### Task 11: CI coverage gate

- [ ] `ci.yml` go job: `-coverprofile=cover.out ./...` + minimum guard (pkg coverage ≥ 60%; only grow).

### Task 12: Release v2.1.0 + second-stage update test (item #8)

- [ ] Full verify; bump single version file + CHANGELOG; `make version`; release publishes bare binaries per arch + sha256; docker build; ghcr push.
- [ ] THEN live second-stage: host holds an OLD 2.0.2 installer-layout binary (serves `frontend/` from disk, old update code). Run `ovm update` there: expect tree migration to the new bare-binary layout, data dir carried, service healthy on 2.1.0, no rollback triggered. Capture verbatim output.


## Sequencing

1 → 4 → 5 → 2 → 3 per value/risk? Correct order (blocking): 1, 2, 3 are independent; 4 depends on Task 1's worker; 5 last (riskiest — touches restore path).

Suggested dispatch: Tasks 1+2+3 parallel (3 lanes), then 4, then 5, release v2.1.0 at end with full verify.

## Review focus

- ACME standalone listener must not fight the panel port; must be optional flag, fail-closed on miss.
- Log endpoint file-path safety (no user-controlled unit string → shell). Whitelist units.
- Kick/propagate idempotency and no partial-failure-and-stuck states.
- Telegram only reads settings, never stores login secrets anywhere beyond .env.
- Restore endpoint double-confirm + statement that data dir is replaced.
