# OVManager — Complete Audit, UI/UX Overhaul, Refactoring & Performance Report

Scope: branch `arena/662f0292-ovmanager`, commit `ae3b577` (on top of `0c79e7b`).
Date: 2026-10-14. All claims below describe work executed in this environment; nothing is inferred or estimated beyond what is labelled as such.

---

## 1. Executive summary

OVManager is a mature product: a FastAPI + SQLAlchemy (SQLite) backend with a React 19 + Vite frontend, a Telegram bot, a CLI (`ovm`), and a hardened OVNode integration. The audit found it already strong on security and backend efficiency (bounded caches, single-flight jobs, opaque hashed sessions, rate limits with caps, CSP/CSRF middleware, pre-compressed assets, lazy routes/locales). The real debt was concentrated in the **frontend presentation layer**: two conflicting z-index token stacks, ~130 dead or duplicated CSS rules, and two divergent button visual languages (legacy `.btn` with shimmer sweep + hover lift + glow vs. the restrained `ui-btn` primitive). One **genuine backend bug** also surfaced immediately: backup listing order was non-deterministic when file mtimes tie (the test suite failed 1/1053 on this checkout).

Most important improvements:

1. **Fixed the pre-existing test failure** — `stored_backups()`/prune ordering now breaks mtime ties deterministically (newest-first is stable on coarse-granularity filesystems).
2. **One coherent z-scale** — replaced two contradictory elevation blocks (`--z-modal` was simultaneously 1000 and 100) with a single documented scale; modals no longer stack *below* the mobile hamburger, toasts no longer tie with it; every overlay z-index now comes from a token.
3. **Unified button system** — legacy `.btn` family restyled to the design-system language (token heights 44/38 px, no shimmer/lift/glow, token inks); `LoadingButton` now delegates to the shared `Button` primitive (one spinner, one geometry).
4. **Dead-CSS purge** — 31 superseded rule blocks removed from `styles.css`/`index.css` (notification popover ×2, status pills, list tables, empty states, sidebar duplicates), each verified property-by-property against the cascade so effective styling is unchanged.
5. **Clean security/dependency posture confirmed** — `npm audit` (prod): 0 vulnerabilities; `pip-audit`: no known vulnerabilities; no secrets handling regressions.

Net code: **−73 lines** (122 insertions, 195 deletions) across 7 files, with all 1053 backend tests and 74 frontend tests passing (baseline: 1052 passed + **1 failed**).

---

## 2. UI/UX changes

### Audited surface
Every route and component family was reviewed at source level (no browser automation exists in this environment — see §9): Login, Claim/Setup, Dashboard layout + KPI/chart/alert/activity panels, User management (table, bulk bar, row menus, form/detail/extend/sessions modals, node-select download modal), Node management (form modal, drawer), Server stats, Settings (General, Display, Appearance, Defaults, Alerts, Bot, TLS, Backup, Security, System, My activity), Audit log, command palette, notification popover, language picker, toasts, mobile nav/drawer.

### Design-system fixes
- **Layering (tokens.css)** — one ordered z-scale (`--z-nav` 70 → `--z-popover-high` 700). The old second "elevation stack" redefined `--z-drawer/--z-modal/--z-toast` to 90/100/120, silently overriding the first block's 1250/1000/10000. Consequences that were live: modal backdrops (z 100) sat **under** the mobile hamburger (z 120), and the toast stack tied with the hamburger. Hard-coded z-indexes (topbar 110, mobile nav 95, drawer layering 118/119/120, row menu 1000, lang dropdown 200) now reference tokens.
- **Buttons** — one visual language. `.btn` (39 uses), `.btn-sm` (30), `.btn-secondary` (20), `.btn-retry`, `.btn-success`, `.btn-danger` now share `ui-btn` geometry (44 px / 38 px, `--radius-md`, semibold) and restrained motion (state-color transitions, 1 px press) instead of a gradient shimmer sweep, `translateY(-2px)` lift and a 20 px glow. Hover for `.btn-secondary` works again (a stale `!important` color rule had frozen it), and light/dark hover behavior is now identical (was accent-tinted in light, gray in dark).
- **`.btn-secondary`/`.btn-retry`** — four stacked definitions (including `background: transparent` that could never apply) consolidated to one token-based pair; `color: #111` hard-coded ink replaced with `--accent-contrast`.
- **`LoadingButton`** — now a thin adapter over `ui Button` (variant/size mapped from the legacy class strings), removing a third spinner implementation (`.spinner` CSS deleted). All 8 call sites unchanged.

### Interaction and consistency
- Empty states, error states, tables and status pills lost their *conflicting* duplicate definitions (e.g. `.status-pill` had two different paddings/radii/font sizes in one file; `.notification-popover` two different widths/heights/shadows). Effective styles are the later, newer ones — now the only ones.
- Focus visibility, reduced-motion guards and WCAG-AA token contrast were already in place and are preserved (token checks still pass in both themes).

### Intentional, documented visual changes
1. Legacy buttons lose the shimmer/lift/glow (deliberate: the brief forbids excessive gradients/animations).
2. Light-theme secondary buttons use `--surface-2` (#f3f6fb) instead of pure white — standard secondary-button contrast on white cards; hover no longer turns accent-orange in light mode only.
3. Node-drawer (z 130) now stacks above the mobile hamburger (z 120) and below modals (z 200) — previously drawer 90 < hamburger 120. Relative order of drawer < modal < toast is preserved.

---

## 3. Code refactoring

- **`backend/routers/maintenance.py`** — added `_backup_sort_key()` (`(mtime, name)`); used by both `stored_backups()` and the retention prune. Fixes the unstable "newest first" order (names embed `YYYYmmdd_HHMMSS`, so name ties break chronologically within a label).
- **CSS dead-code purge** — 31 rule blocks removed (26 in `styles.css`, 5 in `index.css`) after a per-property cascade analysis (shorthand-aware, importance-aware, media-context-aware). Two deletions from the first automated pass were found unsafe on re-audit (`.notice.*` `border-color`, mobile `.ops-main-content` padding) and were restored/merged; behavior is preserved.
- **Token consolidation** — removed the duplicate elevation stack and its unused `--z-dropdown/--z-sticky/--z-tooltip` aliases.
- **Button/LoadingButton consolidation** — one primitive (`ui Button`) behind both entry points.
- **Dependency review** — no dependency removed: `react-icons` (tree-shaken per-icon imports), `qrcode` (dynamic import → separate 23 kB chunk), i18n locales (lazy chunks) are all genuinely used. `npm audit` and `pip-audit` are clean.

Remaining duplication documented in §9 (split rules across `index.css`/`styles.css`, radius values outside the token scale in legacy CSS).

---

## 4. Performance results

Environment: 2-core sandbox, Node 22.22, Python 3.11.2 venv (see §9 for interpreter note), single uvicorn worker.

| Metric | Before | After |
|---|---|---|
| Frontend `index.*.css` (initial) | 112.58 kB / 19.80 kB gzip | **110.69 kB / 19.50 kB gzip** |
| Frontend `index.*.js` (initial) | 318.04 kB / 103.23 kB gzip | 318.04 kB / 103.24 kB gzip (unchanged) |
| Backend test suite | 1052 passed, **1 failed**, 12 skipped (78 s) | **1053 passed, 0 failed**, 12 skipped (78 s) |
| Frontend tests | 74 passed | 74 passed |
| App import + composition | — | 989 ms, 84 MB peak RSS (probe) |
| uvicorn idle (scheduler on, no nodes) | — | RSS ≈ 93 MB, CPU ≈ 0–1.7 % |
| `GET /health` latency | — | 0.9–1.1 ms (5 samples) |

Backend optimization review (measured/inspected, largely already excellent): live data comes from one background collector + in-memory snapshot (no request-time fan-out); APScheduler jobs are single-flight with coalescing; login/subscription rate-limit buckets are capped (10 k) and purged; `_rpc_last_error`/`_tls_fallback_warned` maps capped; `_pinned_sessions` bounded by node count; index.html served from a stat-keyed cache; assets served pre-compressed with immutable caching; SSE uses plain-ASGI middleware (no BaseHTTPMiddleware buffering). No additional optimization was justified by evidence — none was applied that could slow interactions.

Not measured here (needs a production-like deployment): API p95/p99 under concurrent load, multi-node collector cost at N nodes, memory growth over days.

---

## 5. Security review

Confirmed strengths (verified in source + tests): opaque session tokens stored as SHA-256, sliding idle + absolute expiry, per-account revocation; bcrypt with timing-safe dummy verify on unknown users; rate limits (per IP/user/pair) with `Retry-After`, bounded memory; hashed IPs in rate-limit keys; CSRF middleware (`X-Requested-With` + bearer carve-outs); strict CSP with pinned inline-script hash; empty-404 outside the secret URL prefix; asset path traversal defended (realpath containment + tests); backup files `0600`, data dir `0700`; TLS verification with explicit, warned self-signed fallback; panel↔node requests carry `X-Panel-ID` with 409 surfacing.

Fixes in this pass: none required in auth/authz paths; the backup-ordering fix removes a listing non-determinism (restore target ambiguity when timestamps tie).

Audits run: `npm audit --omit=dev` → **0 vulnerabilities**; `pip-audit` → **no known vulnerabilities**.

Remaining risks (unchanged, documented): in-memory rate limiting resets on restart (single-process design); `CORS_ORIGINS` is env-configured and empty by default (correct); node API keys live in the DB by design (0600 data dir).

---

## 6. Integration compatibility (OVNode)

OVNode source is not in this repository and was not modified or assumed. From OVManager's client (`backend/node/requests.py`, `sync.py`, `fanout.py`, `management.py`): HTTP to `address:port` with TLS pinning (`check_hostname` off, pin to node CA), 10 s/30 s timeouts, capped 429 `Retry-After` handling, `X-Panel-ID` header, lifetime-byte counter accounting. **No integration contract changed in this pass** — the only backend change is panel-local backup listing/pruning order. No follow-up in OVNode is required.

---

## 7. Testing report

| Check | Command | Result |
|---|---|---|
| Backend suite | `.venv/bin/python -m pytest tests/ -q` | **PASS** — 1053 passed, 12 skipped (baseline had 1 failure: `test_cli_backup.py::test_restore_without_a_name_lists_backups_with_dates_and_sizes`, now passing) |
| Frontend full gate | `npm run verify` (build + check:tokens + check:i18n + check:rtl + eslint + tsc + vitest) | **PASS** — 74/74 tests, tokens WCAG-AA in both themes, i18n 0 missing, RTL clean |
| Backend lint | `make lint-backend` (ruff check + format --check + bash -n + git diff --check) | **PASS** |
| Frontend lint | `npx eslint src/` | **PASS** |
| Production build | `npm run build` | **PASS** (469 ms, precompressed assets emitted) |
| Dependency audits | `npm audit --omit=dev`, `python -m pip_audit` | **PASS** — 0 / 0 findings |
| Rendered-browser inspection | — | **NOT RUN** — no browser automation available in this sandbox (see §9) |
| Load/perf benchmarks | — | **PARTIAL** — startup, idle RSS, `/health` latency measured; p95/p99 under load not run |

Note: the backend venv runs **Python 3.11.2** (the sandbox cannot download a 3.12 interpreter — GitHub release assets blocked; `pyproject.toml` requires ≥3.12). The suite is green on 3.11, which is a lower bound; run `uv sync --frozen && make test` on 3.12 for the canonical result.

---

## 8. Files changed (commit `ae3b577`)

| File | Purpose |
|---|---|
| `backend/routers/maintenance.py` | `_backup_sort_key()`: deterministic newest-first ordering (fixes failing test; mtime ties broken by name) |
| `frontend/src/tokens.css` | Single z-scale (13 layers); removed conflicting elevation block + unused z-aliases |
| `frontend/src/index.css` | `.btn` family restyled to design-system language (no shimmer/lift/glow); z-indexes → tokens; dead rules removed (`.spinner`, sidebar dups) |
| `frontend/src/styles.css` | 26 dead rule blocks removed; `.btn-secondary`/`.btn-retry` consolidated; `.notice.*` merged faithfully; z-indexes → tokens; layering comments updated |
| `frontend/src/pages/UserManagement.css` | Row-menu z-index → `--z-popover` |
| `frontend/src/components/LoadingButton.tsx` | Delegates to `ui Button` (shared spinner/geometry/variants) |
| `frontend/src/components/ui/Button.css` | Added filled `ui-btn--success` variant |

---

## 9. Remaining limitations

1. **No real-browser verification** — this environment has no browser automation; UI changes were verified via DOM tests, CSS cascade analysis, and the build/token/i18n gates. Desktop + mobile screenshots in a browser should be done before release.
2. **Split CSS ownership** — ~30 selectors still carry properties across both `index.css` and `styles.css` (e.g. `.icon-btn`, `.toast`, `.ops-topbar-minimal`). Full consolidation is safe only with visual regression coverage; left as documented debt.
3. **Legacy radius values** — older CSS still uses raw 4/6/7/8/9/10/12/14 px radii alongside the token scale; normalizing them is cosmetic churn without pixel-diff tooling.
4. **Load metrics** — p50/p95/p99 API latency under concurrent use, and collector cost with many nodes, were not measurable here.
5. **Python 3.12 canonical run** — suite green on 3.11.2; re-run on the project's declared 3.12 when available.
6. **Per-page layout redesign** — pages already run on the `ui-` component family (PageHeader/Card/DataTable/Tabs/Field/Badge/StatCard) and were audited; deep information-architecture restructuring (beyond the design-system fixes above) would need rendered testing to be responsible.

## 10. Deployment considerations

- **No migrations, no config changes, no API/protocol changes.** Standard release path only: `npm run build` for the SPA (CI already does), package as usual.
- Behavior notes to mention in release notes: button hover animations removed (intentional); light-theme secondary buttons are light-gray instead of white; toasts now reliably above page chrome; modals above the mobile hamburger; node drawer above the hamburger on phones.
- Rollback: none needed (no schema/config). Reverting commit `ae3b577` restores prior visuals exactly.
