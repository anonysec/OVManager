# OVManager — Full Project Review (post-merge 2026-10-19)

Scope: whole repo at `main` `d74bdc1` (Go backend + React SPA + installer/Docker/CI + docs). Read-only inspection; nothing modified. Consolidates lanes A–F. Severity tiers: 🔴 blocking, 🟡 important, 🟢 medium/low, 📝 note.

## Gates (all green on merged tree)
- Go: `go build ./...` ok, `go vet ./...` ok, `gofmt -l .` empty, `go test ./...` 6/6 ok (32s). Note: two earlier failures (`TestDBRestoreRejectsOversize`, `TestBinaryServesPanel`) were caused by `/tmp` at 99% (leftover 101MB multipart files), not code — both pass after cleanup.
- Web: `npm run build` ok, `check:types` ok, `eslint src/` 0 errors, `vitest` 12 files / 67 tests pass, `check:tokens`/`check:i18n`/`check:rtl` pass.
- Coverage: 55.1% (internal/ + cmd/). Weakest: acme 0%, webfs 0%, cli 42%, node 46%, db 48%.

---

## 🔴 CRITICAL (blocking)

1. **[panel.go:138-140] `MountSub` registers `subStaticJS`/`subDownload`/`subPage` with NO auth wrapper** — serves OVPN client configs + per-user subscription data to anyone reaching the subscription path; `subUser` (sub.go:280) keys purely on UUID. Evidence: bare `mux.HandleFunc("GET "+prefix+"/download/{uuid}/{node_name}", h.subDownload)` etc. Fix: wrap all three with `RequireUser`/`RequireOwner` (or session check inside `subUser`). *(Lane C)*

## 🟡 HIGH (important)

2. **[panel.go:58-59] `/health/setup` and `/health/tls` use `user()` not `owner()`** — exposes server settings/health to any authenticated user while every sibling `/health/*` requires owner. Fix: switch to `owner()`. *(Lane C)*

3. **[auth/handler.go:148-169] No CSRF/Origin/Referer validation anywhere** — every state-changing POST (`/maintenance/*`, `/tls/*`, `/updater/*`, `/server/*`, db backup/restore) accepts cross-origin form posts behind only the session cookie. Evidence: grep finds only `SameSite: Lax` (auth/handler.go:97). Fix: per-session CSRF token or Origin/Referer match on mutating endpoints. *(Lane C)*

4. **[telemetry/handler.go:396-408, 576-585] Unchecked type asserts on node-sourced data** in `CollectMetrics` and `CollectLiveSnapshot` (`live, _ := sessions["live_sessions"].([]any)`, `sess, _ := item.(map[string]any)`) — a malformed node payload can panic the live collector. Fix: ok-checks/type-switch, skip/record bad frames. *(Lane C)*

5. **[internal/node/traffic.go:75] SyncTraffic silently skips billing when node reports numeric CN keys** — `ExtractUsername` handles name + `<name>-<node>` suffix but NOT numeric panel user ids, while the live collector (`telemetry/handler.go:519-584`) maps `"42" → alice` via `idToName`. A numeric usage key fails `known` check and is dropped forever with no counter. Fix: build id→name map in `loadTrafficUsers` and resolve before `ExtractUsername` (~6 lines). *(Lane A)*

6. **[web/src/context/LiveContext.tsx:15-38] SSE `readEventStream` discards the `data:` KV payload** — only `topic` is broadcast; `{"op":...}` body dropped, forcing full refetches on every live event. Fix: parse `data:` lines, pass parsed object to `onEvent(topic, data)`. *(Lane D)*

7. **[CHANGELOG.md] Missing entries for all post-2.1.2 work** — traffic accounting, live snapshot, race fixes merged 2026-10-19 are absent from CHANGELOG (2.1.2 bumped 2026-10-18 21:53, before those commits). Release contract silently incomplete. *(Lane E)*

8. **[README.md:77] Port mismatch 2083 vs actual 2095** — README says "`2083` is the only port", actual is 2095 everywhere (Dockerfile:36, install.sh:32, README:108, panel.go:249). Operator confusion / firewall misconfig. *(Lane E)*

## 🟢 MEDIUM (should fix)

9. **[db/migrate.go:808-848] All node keys decrypt under one global key** (`NODE_ENCRYPT_KEY` → `BOT_KEY` fallback), then stored plaintext after migration — one key compromise exposes every node key. Fix: per-node wrapping + rotate. *(Lane C)*

10. **[node/client.go:171,265,663] `InsecureSkipVerify: true` TLS fallback paths** — MITM on panel→node control channel when pin verification fails. Fix: remove insecure fallbacks, require pinned/verified peer cert. *(Lane C)*

11. **[telemetry/stream.go:211] `StreamHandler` inline `CurrentUser` check** instead of `RequireUser`/`RequireOwner` wrapper — protected but pattern-inconsistent; future SSE route could skip. *(Lane C)*

12. **[users/handler.go:457, panel/maintenance.go:706] Reset writes `node_usage` without OCC guard** — a traffic pass landing between read and write clobbers the just-written baseline; next pass re-bills. Window is admin-call vs ~60s tick. Fix: same `COALESCE(node_usage,'{}') IS ?` guard + retry. *(Lane A)*

13. **[go.mod:3 vs README:12/install.sh:341] Go version mismatch 1.26 vs 1.27** — README badge and installer say 1.27+, go.mod says 1.26.0. *(Lane E)*

14. **[9 env vars undocumented]** — `OVM_APP_DIR`, `DATA_DIR`, `NODE_TLS_INSECURE_FALLBACK`, `OVM_REPO`, `OVM_PANEL_USER`, `OVM_ADMIN_PASS`, `OVM_ACME_DOMAIN`, `OVM_ACME_DIRECTORY_URL`, `OVM_ACME_HTTP_PORT` read in Go but absent from `.env.example`/README/SECURITY. *(Lane E)*

15. **[Dockerfile:15,28] Base images not pinned by digest + no HEALTHCHECK** — CVE exposure via stale layers, no container health signal. *(Lane E)*

16. **[web/src/services/api.ts:115-119, UserManagement.tsx:389-397] `AbortController` time-bound only, not unmount-bound**; `handleShowSessions` has no in-flight guard. Fix: abort on unmount / add cancelled guard. *(Lane D)*

17. **[web/src/pages/UserManagement.tsx:111,145] `fetchUsers` depends on `users.length`** while mount effect re-runs on `fetchUsers` change → extra refetch per mount. Fix: drop `users.length` from deps. *(Lane D)*

18. **[test coverage skew] `/sub/*`, `POST /tls/*`, `POST /https/*` aliases have unclear/no Go coverage** (panel_test.go truncated at 328; sub/* not covered by unit or e2e). Security-relevant: sub/* serves OVPN configs. *(Lane E)*

19. **[auth/handler.go:86-98] Session cookie `Secure` conditional on `r.TLS`** — over plain HTTP or mis-terminated TLS the cookie travels without Secure. *(Lane C)*

20. **[install.sh:96-99] Installer delivered as `curl|bash`** of remote script (binary checksummed, script itself not). *(Lane C)*

## 🟢 LOW

21. **[panel/sub.go:229-252] `subDownload` serves OVPN configs keyed solely by subscription UUID** (bearer link) — intended design; pair with route-level auth (#1) so the link is the only secret; keep per-IP rate limit. *(Lane C)*
22. **[web/src/context/LiveContext.tsx:95, ServerStats.tsx:205, DashboardLayout.tsx:293] Empty-catch error swallows** — data-fetch/resource failures silently ignored. *(Lane D)*
23. **[web/src/pages/UserSessionsModal.tsx:51,73] `<tr key={i}>`** index keys for nodes/registry arrays. *(Lane D)*
24. **[136 unused i18n keys + 5 unused CSS vars + stubbed `/users/{uuid}/sessions` endpoint]** — dead weight from removed TLS/health/admin features; checker passes because it only checks missing/extra vs `en`, not usage. *(Lane D)*
25. **[web test coverage]** — no tests for user table with live fields, Settings save-on-modal, SSE reconnect, TopUsers/StreamChart formatting. *(Lane D)*
26. **[node/client.go:245,253,265,631] Per-call `http.Transport` allocation, no `CloseIdleConnections`** — connection-pool/FD churn. *(Lane F)*
27. **[install.sh] Requires root, no `--prefix` flag**; no `make release`/`make image` targets (release only via GitHub Actions). *(Lane E)*

## 📝 NOTES

28. **[Lane A F3] No `recover` in any worker goroutine** (traffic_worker, live_worker, tls_acme, notify/telegram) — a panic in a tick takes the whole panel down. Consistent with existing house pattern (ACME/Telegram predate this merge); report pattern-level, not blocking. If added, use the existing `runTrafficSync`/`runLiveCollect` seams. *(Lane A)*
29. **[Lane A F4] Live poll env vars ignore `.env`** — `PollSeconds`/`idlePollSeconds` use `os.Getenv` only, while `trafficPollSeconds` uses `envOrFile`. Align or document. *(Lane A)*
30. **[Lane A F5] `aggregateNodeUsage` numeric-key corner** — a numeric key that is not a live node id (deleted node) still totals under its raw key; defensible (history shouldn't vanish). *(Lane A)*
31. **[Lane C nits] Verified safe**: `setColumns` allowlisted columns (panel.go:369); `cleanupCandidates` hardcoded WHERE (maintenance.go:550-559); telemetry DELETE hardcoded table list (telemetry/handler.go:431); no hardcoded secrets; no pprof/debug/metrics public endpoint; `modernc.org/sqlite v1.60.1` pinned, no `replace`. *(Lane C)*
32. **[Lane F] All 5 green-bug traps verified clean** (OCC retry, idle windows 30/300+env45, billing rollback, users live() counts, reserved-key omission). No confirmed prod-code bugs beyond B1 transport churn. *(Lane F)*

---

## Top 3 if I only had 10 minutes (risk × effort)

1. **Add the auth wrapper to `MountSub` routes** (panel.go:138-140) — 🔴 CRITICAL, trivial effort: one `RequireUser`/`RequireOwner` per route stops unauthenticated OVPN config + subscription-data exposure.
2. **Guard the type asserts in `CollectMetrics`/`CollectLiveSnapshot`** (telemetry/handler.go:396-408, 576-585) — 🟡 HIGH, low effort: ok-checks/type-switch prevent a malformed node payload from panicking the live collector.
3. **Add CSRF/Origin protection on mutating POSTs** (panel.go:73-108, auth/handler.go:148-169) — 🟡 HIGH, medium effort: closes cross-origin state-changing attacks across every maintenance/TLS/updater/db endpoint.

Next tier (if 30 more minutes): #5 SyncTraffic numeric-CN billing alignment, #6 SSE data payload parse, #7 CHANGELOG backfill, #8 README port fix.

Merged workload (traffic accounting + live snapshot) is clean; anything in this report is the consolidated project picture, not a blocker for the merged feature.
