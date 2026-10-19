# OVManager SPA / API cross-review

Read-only review. No files modified. Source of truth: `web/src/**`, `web/e2e/**`, `web/scripts/**`; backend JSON handlers in `internal/{panel,users,telemetry,billing,node}/`.

## 1) CROSS-KEYS drift (backend JSON <-> SPA types/consumers)

The SPA has NO `web/src/types/**` domain models — every response is read `any` through `services/api.ts` (`ApiResponse<T = any>`, api.ts:30) and unpacked ad hoc with `asList` (utils/apiData.ts:5) / `r.data?.data?....`. There is no central type contract to drift against; drift is detected by matching backend JSON keys to consuming component reads.

### (a) Backend fields the SPA never displays (dead weight)

- `id` in `userRow.base()` — `internal/users/handler.go:100` (`"id": u.ID`). SPA keys every user by `uuid` (UserManagement.tsx:76 `Set<string>()`, rowKey `String(r.uuid)` line 760, URLs `/users/${user.uuid}` line 305). `id` is never read by any component.
- `per_node` from `GET /users/{uuid}/traffic` — `internal/users/handler.go:619` (`"per_node": perNode`). UserDetailModal.tsx fetches this endpoint (line 57) but only reads `days` (60), `total_used` (62), `used` (92), `total` (93). `per_node` is never rendered.
- `online_users`, `active_users`, `total_users` in `traffic_snapshots` — `internal/telemetry/handler.go:274-276`. StreamChart.tsx consumes only `ts`, `total_used`, `active_connections` (StreamChart.tsx:36, 96); the three user-count fields are never plotted.
- `sessions` / `active` from `GET /users/{uuid}/sessions` — `internal/users/handler.go:180-181` returns hardcoded `{"sessions": [], "active": 0}` (Phase 2 stub). UserSessionsModal.tsx reads `data?.active_connections` / `data?.totals?.live_count` (lines 22) but the endpoint emits neither — modal shows "Active/Max: 0/∞" forever behind a stub.

### (b) SPA fields with no matching backend emitter (UI shows "—" forever / stubbed)

- `UserSessionsModal` `active`/`max`: backend `/sessions` is a stub (handler.go:180-181) emitting `active: 0`, no `active_connections`/`totals`. Modal falls back to `0/∞` (UserSessionsModal.tsx:22-23) — reads a value the backend never produces for this endpoint.
- No live data field was found hardcoded `"—"` with an emitter; the clearest "SPA expects, backend never emits" surface is the removed-feature i18n keys (settingsTls*, health*, auditTime*, admins*, updateAvailable*) — 136 keys unused in source (see §3). The check:i18n checker does NOT flag these because it only enforces missing/extra vs `en.json`, not usage.

### (c) Units/naming drift — raw BYTES vs SPA formatting

Backend `TopUsers`/`UserDailySeries`/`used`/`total` return raw BYTES: `internal/billing/ledger.go:121` (`"bytes": bytes`), `ledger.go:97` (`"bytes": have[d]`), `internal/users/handler.go:618-621` (`"used": deref(row.Used)`, `"total_used": total`, `"total": row.Total`).

SPA `formatBytes` uses binary 1024 (utils/format.ts:4-9):
```
const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
```
Consumed by UserDetailModal.tsx:123, 153; TopUsers.tsx:34; StreamChart.tsx:125-127; ServerStats.tsx:439, 480, 488. **No wrong multiplier** — 1024-based binary matches backend bytes. Sidebar's inline `formatUsage` (Sidebar.tsx:134-138) is also 1024-based. UserFormModal/ExtendUserModal convert GB→bytes via `* 1024 * 1024 * 1024` (UserFormModal.tsx:14, ExtendUserModal.tsx:35) — binary, consistent with backend bytes.

### Verified consistent (checked, match)

1. `active_connections` / `online` live fields — backend `internal/users/handler.go:121-122` (just merged, commit 9aaa6cf: `m["active_connections"] = count; m["online"] = count > 0`) ↔ SPA consumes: UserManagement.tsx:32, 42 (`u.online || Number(u.active_connections || 0) > 0`), 156 (`userStats.online`), 239 (sort), 591-593 (render `${active_connections}/${max_logins}`).
2. `topTraffic` `name`/`bytes` — backend `internal/billing/ledger.go:121` ↔ SPA `components/dashboard/TopUsers.tsx:13` (`r.bytes || 0`), 34 (`formatBytes(r.bytes || 0)`).
3. `UserDailySeries` `day`/`bytes` — backend `internal/billing/ledger.go:97` ↔ SPA `components/UserDetailModal.tsx:60` (`r.data?.data?.days`), 34 (`formatBytes(d.bytes)`).
4. `metricsHistory` traffic `ts`/`total_used`/`active_connections` — backend `internal/telemetry/handler.go:274-276` ↔ SPA `components/dashboard/StreamChart.tsx:36` (`p.total_used`, `p.active_connections`), 96 (`r.data?.data?.traffic`).
5. `server/info` `cpu`/`memory_used`/`memory_total`/`disk_used`/`disk_percent`/`uptime` — backend `internal/panel/setting.go:541-563` ↔ SPA `pages/ServerStats.tsx:254-256`, 471, 480-488, 496 (`formatBytes(stats.memory_used)`, `formatUptime(stats.uptime)`).

## 2) Architecture / lifecycle bugs (data-fetch & resource lifecycle)

### A) SSE `readEventStream` discards the `data:` KV payload — `web/src/context/LiveContext.tsx:15-38`
```
while ((idx = buf.indexOf('\n\n')) !== -1) {
  const block = buf.slice(0, idx);
  ...
  let topic = null;
  for (const line of block.split('\n')) {
    const trimmed = line.trim();
    if (trimmed.startsWith('event:')) topic = trimmed.slice(6).trim();
  }
  onEvent(topic);   // <-- topic only; KV{"op","ts",...} body is dropped
}
```
The SSE frames carry `event: <topic>\ndata: <json>` (Go `internal/telemetry/stream.go:252-257` appends `{"ts":...}` to `data`). The SPA receives only `topic`; `tickWithPublish(topic)` (LiveContext.tsx:63-70) broadcasts a bare topic with no payload. Every subscriber (`users.changed`, `tick`, etc.) must refetch wholesale instead of applying a surgical delta. Not data corruption, but defeats the purpose of the KV shape and forces full refetches on every live event.

### B) Empty-catch error swallows — data-fetch / resource lifecycle
- `LiveContext.tsx:95`: `} catch { /* retry below */ }` — stream failure reason discarded; reconnect scheduled blindly (line 99 `setTimeout(connect, RECONNECT_MS)`).
- `ServerStats.tsx:205`: `} catch { /* keep previous */ }` — node probe failures silently ignored.
- `DashboardLayout.tsx:293`: `} catch { /* keep existing */ }` — notification build failures silently keep stale notifications.
- `api.ts:120-129` converts network/abort errors to dispatched `api:error` events (good), but callers that empty-catch (above) never surface them.

### C) `AbortSignal` not tied to component unmount — `web/src/services/api.ts:115-119`
```
const ctrl = new AbortController();
const timer = setTimeout(() => ctrl.abort(), timeout);
res = await fetch(fullUrl, { ..., signal: ctrl.signal });
```
The controller is only time-bound (30s), never linked to React unmount. `UserDetailModal` guards with a `cancelled` flag (lines 55, 68-70) and `UserSessionsModal`-driven `UserManagement.handleShowSessions` has no in-flight guard (UserManagement.tsx:389-397), so a navigation-away mid-fetch still calls `setSessionDiagnostics` (React 19 tolerates, but wasted work + no cleanup). `LiveContext` does abort on unmount correctly (`abortRef.current?.abort()`, line 106) — the asymmetry is the api layer.

### D) React 19 hook-dep gotcha — `web/src/pages/UserManagement.tsx:97-111`
```
const fetchUsers = useCallback(async ({ background = false } = {}) => { ... }, [addToast, users.length, t]);
...
useEffect(() => { fetchUsers(); fetchSubSettings(); fetchMyDefaults(); }, [fetchUsers, fetchSubSettings, fetchMyDefaults]);  // line 145
```
`fetchUsers` depends on `users.length`; it calls `setUsers`, so after the first fetch the callback identity changes → effect re-runs → one extra fetch per mount (bounded, not infinite, because equal-length lists restabilize). Wasteful and fragile: adding any non-primitive dep would loop.

### E) key props in conditional JSX / index keys
`UserSessionsModal.tsx:51` `<tr key={i}>` and 73 `<tr key={i}>` use array index as key for `nodes`/`registry`; stable only while order is fixed. `DataTable` rowKey uses `uuid` (correct) — no index-key issue there.

### F) Token-bound text-color (theme) — not a violation
`ThemeContext.tsx` drives everything through `data-theme` + CSS `var(--text-*)` (lines 30-36, 54, 72-74, 101-103). Inline `style={{ color: 'var(--text-primary, ...)' }}` (ErrorBoundary.tsx:43, ConfirmModal.tsx:26, Logo.tsx:17) uses CSS var fallbacks, not hardcoded hex — tokens respected. No `setColorScheme` bypass exists in the SPA. **Checked clean.**

### G) Refetch on tab-visible — bounded but simultaneous
`ServerStats.tsx:226` and `DashboardLayout.tsx:302` gate refetch on `document.visibilityState === 'visible'` (good). `LiveContext` also publishes `tick` on visibility (lines 116-122), so every LiveContext subscriber (UserManagement background fetch, ServerStats `loadData`) refetches at once when the tab regains focus — a mild refetch storm, bounded by `DATA_REFRESH_SEC`, not unbounded.

### H) SSE reconnect / token-storm on refresh
Each `LiveProvider` mount opens its own SSE to `/live/stream` (LiveContext.tsx:86) and there is no cross-tab / dedup logic. On hard refresh the old stream is aborted (cleanup line 106) and a new one opens — no leak per session, but no backoff jitter: `RECONNECT_MS = 20000` fixed (line 11). On mass refresh all clients reconnect in lockstep. Minor; acceptable for single-operator panel.

## 3) Dead / dead-end code (~10 concrete misses)

### Unused i18n keys (136 of 871 in `en.json` — dead weight from removed TLS/health/admin features)
`scripts/check-i18n.mjs` PASSES (fa/ru/cn in sync, no extra keys) because it only checks missing/extra vs `en`, not whether a key is referenced in source. A quote-based scan found these keys never appear as `t('...')` in any `.ts/.tsx/.css`:
`settingsTls`, `settingsTlsDesc`, `settingsTlsCard`, `settingsTlsMode`, `settingsTlsCertFile`, `settingsTlsMode_managed`, `settingsTlsMode_files`, `settingsTlsRestartRequired`, `settingsTlsRestartConfirm`, `settingsTlsRestarting`, `settingsTlsRenewButton`, `settingsTlsAcmeButton`, `healthTitle`, `healthSubtitle`, `healthRefresh`, `healthEmpty`, `auditTime_all`, `auditTime_1h`, `auditTime_24h`, `admins`, `addNewAdmin`, `updateAvailableTitle`, `updateRunning`, `cleanStale`, `panelDomain`, ... (136 total). The checker does **not** misspell anything — it simply doesn't check usage, so these pass silently.

### Unused CSS vars (defined in `tokens.css`, referenced nowhere)
Spot-check of 10, 5 confirmed defined-but-never-used (only appear in `tokens.css`):
- `--background-card-hover` (tokens.css:267, `var(--surface-3)`)
- `--card-base-bg` (tokens.css:268, `var(--surface-1)`)
- `--text-2` (tokens.css:250, `var(--text-secondary)`)
- `--warning-color` (tokens.css:263, `var(--warning-text)`)
- `--info-color` (tokens.css:262, `var(--info-text)`)
The other 5 spot-checked (`--border-color`, `--body-bg`, `--danger-color`, `--cyan`, `--orange`) ARE referenced. No `check:tokens` failure (passes) — it checks resolveability, not usage.

### Dead-end backend feature
`GET /users/{uuid}/sessions` is a Phase 2 stub returning hardcoded `{"sessions": [], "active": 0}` (`internal/users/handler.go:180-181`). `UserSessionsModal` renders against it and shows zeros forever — frontend is wired to a non-emitting endpoint.

### Components / services — all wired
Verified importers for `RouteProgress`, `SectionBoundary`, `StatCard`, `EmptyState`, `ErrorState`, `PageHeader`, `Badge`, `Tabs`, `KpiCard`, `Panel`, `PanelState`, `PanelSkeleton`, `SkeletonBlock`, `SkeletonPanel` — all have ≥1 importer. Verified callers for `getUiPref`, `setUiPref`, `applyAccent`, `readPrefs`, `writePref`, `alertPrefKey`, `copyText` — all have ≥2 callers. No orphaned components or unused service functions found.

## 4) Tests quality

`npm run test` (vitest) passes. Test files: `App.setupRedirect.test.tsx`, `breakpoints.test.ts`, `useAsyncData.test.ts`, `ClaimPage.error.test.tsx`, `ServerStats.dom.test.tsx`, `settingsButtonScope.test.ts`, `SetupWizard.auto.test.tsx`, `UserManagement.ux.test.tsx`, plus `apiData`/`displayTimezone`/`errorMessage`/`geo` util tests.

Coverage: `App.reset`/`Breakpoints` redirect flow IS tested (`App.setupRedirect.test.tsx`). `UserManagement.ux.test.tsx` tests search debounce + tag chips only, with `LiveContext`/`AuthContext`/`api` mocked and NO `active_connections`/`online` data (fixtures use `total: null, used: 0`, line 36). `ServerStats.dom.test.tsx` tests per-source error isolation, not traffic rendering.

**Key flows with NO test coverage:**
- User table rendering with the new `active_connections`/`online` fields (status badge, sessions column, online stat).
- Account/Settings page usage moment recording (no Settings save-on-modal test).
- Settings save-on-modal (GeneralSection/DisplaySection/etc. have no tests).
- SSE reconnect behavior / token-storm on refresh (`LiveContext` unreachable in tests — mocked out in every component test).
- `TopUsers` bytes formatting / `StreamChart` counter-delta bucketing.

## 10-minute triage — top 3 fixes

1. **[high] `web/src/context/LiveContext.tsx:15-38`** — SSE drops the KV `data:` payload, so `{"op":...}` invalidations carry no data and every subscriber full-refetches. Fix: parse `data:` lines and pass the parsed object to `onEvent(topic, data)`; let subscribers apply surgical updates instead of refetching everything on any tick.
2. **[high] `web/src/services/api.ts:115-119` + `web/src/pages/UserManagement.tsx:389-397`** — fetch `AbortController` is time-bound only, not unmount-bound, and `handleShowSessions` has no in-flight guard. Fix: abort in-flight fetches on unmount (tie `AbortController` to component lifetime or add a `cancelled` guard in `handleShowSessions`/`fetchUsers`).
3. **[medium] `web/src/pages/UserManagement.tsx:111,145`** — `fetchUsers` useCallback depends on `users.length` while the mount effect re-runs on `fetchUsers` change → extra refetch per mount and live-tick re-subscription churn. Fix: remove `users.length` from `fetchUsers` deps (it reads `users` only inside `setIsLoading` ternary) or split the live-subscribe effect from the fetch effect.

Dead-weight to prune later (not blocking): 136 unused i18n keys, 5 unused CSS vars, and the stubbed `/users/{uuid}/sessions` endpoint feeding `UserSessionsModal`.
