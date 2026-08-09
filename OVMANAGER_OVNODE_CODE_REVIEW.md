# OVManager + OVNode full code review

**Review basis**

> The findings below describe the baseline reviewed before the remediation pass. The current workspace now contains fixes for the main P0/P1 items; run the validation commands shown in the assistant handoff to verify them.

- OVManager repository: `8daa519` (`8daa519276983286e5652073751dc9359a41d0e3`) plus the current uncommitted working tree, including the UI/UX changes in this workspace.
- OVNode repository: `7c8a493` (`7c8a4938f797c8c23058cc5a06ab204cd49cbc83`), clean checkout.
- Scope: authentication and authorization, Manager↔Node API contracts, OpenVPN/PKI lifecycle, data integrity, deployment/installers, frontend/API behavior, performance, tests, and CI.

## Remediation pass completed in this workspace

The following baseline findings were addressed in the current working tree: CRL/disabled-user enforcement scaffolding, usage/status/config contract alignment, user ownership checks, access-vs-refresh JWT separation, logout revocation, bot-token response hardening, persistent data-path centralization, Docker packaging order, installer `eval` removal/default-password refusal, URLPATH fail-open reduction, frontend reset/backup endpoint fixes, bounded OVNode rate limiting, and portable OVNode test paths. The complete end-to-end OpenVPN revocation/reconnect path still requires a real OpenVPN integration environment.

## Executive summary

The architecture is understandable and has several good hardening measures, but the current Manager↔Node combination is **not ready for public production exposure**. There are multiple release-blocking issues:

1. **Deleting or disabling a client does not reliably revoke/deny an already-issued OpenVPN certificate.** The default OVNode server configuration does not enable CRL verification, and disabling a user only removes a CCD file.
2. **The Manager and Node contracts are out of sync.** Traffic collection asks `/sync/status` for usage data, node status response names do not match what the frontend consumes, and the Add/Edit Node settings are never sent to OVNode’s `/sync/config` endpoint.
3. **Authorization is inconsistent.** Several Manager user mutation endpoints do not enforce ownership for regular admins.
4. **JWT refresh tokens are accepted as normal API bearer tokens, are not rotated, and are stored in `localStorage`.**
5. **The supplied Manager Dockerfile is not buildable/reliable as written, and the configured `DATA_DIR` is ignored by the database/logger paths.**
6. **Both installers execute user-controlled values through `eval` while running as root and have unsafe default credential behavior.**

Recommended release decision: **No-go until all P0 items are fixed and covered by integration tests.**

---

## Findings by severity

### P0 / Critical — release blockers

#### C-01 — OVNode certificate revocation and disable enforcement are incomplete

**Evidence**

- `ovnode/core/pki_setup.py:151-187` writes the default `server.conf`, but does not add `crl-verify .../crl.pem`.
- `ovnode/core/service/user_management.py:204-234` calls EasyRSA revoke and generates a CRL, but ignores the Boolean result from `_easyrsa()`.
- `ovnode/core/service/user_management.py:237-267` implements disable by deleting the client’s CCD file only.

**Impact**

- A client with an already-issued certificate may continue to connect because OpenVPN is not configured to consult the generated CRL.
- Removing a CCD file is not an authentication denial mechanism; the absence of per-client configuration does not inherently reject a certificate.
- A revoked/deleted user can remain connected unless explicitly disconnected, and a disabled user may reconnect with an existing profile.

**Fix**

- Add and verify `crl-verify /etc/openvpn/server/pki/crl.pem` in the server configuration.
- Fail the revoke operation if either revoke or CRL generation fails.
- Reload OpenVPN after CRL changes.
- On disable/expiry: disconnect live sessions, revoke or otherwise deny the certificate, remove the limit/marker state, and verify the new connection is rejected.
- Add an end-to-end test that creates a client, disables it, and proves a reconnect fails.

---

#### C-02 — Traffic accounting calls the wrong OVNode endpoint

**Evidence**

- `ovmanager/backend/node/sync.py:22-25` implements `get_users_used_traffic()` by calling `NodeRequests.get_node_info()`.
- `ovmanager/backend/node/requests.py:49-50` maps `get_node_info()` to `GET /sync/status`.
- `ovnode/core/routers/router.py:62-70` exposes user traffic at `GET /sync/usage`.
- `_collect_node_traffic()` expects `data["users"]` and `data["sessions"]`, but `/sync/status` returns CPU/memory/version status instead.

**Impact**

The scheduled traffic collector normally receives no usage payload, so user traffic totals and traffic-limit enforcement can remain stale or never advance. This also undermines expiry/traffic disable behavior.

**Fix**

Add a dedicated `NodeRequests.get_usage()` calling `/sync/usage`, use it in `get_users_used_traffic()`, and add a contract test with a mocked OVNode response.

---

#### C-03 — Manager node-status response does not match frontend expectations

**Evidence**

- `ovmanager/backend/node/ops.py:98-123` returns `{node, info, sessions}`.
- `frontend/src/pages/ServerStats.jsx:286-305` expects `data.node_info` and `data.session_diagnostics`.
- `frontend/src/pages/NodeManagement.jsx:67-73` also only stores `data.node_info`.

**Impact**

The dashboard and Nodes page can classify healthy nodes as unreachable and show empty CPU/session data. The alert center can report false node outage alerts.

**Fix**

Choose one canonical response schema and use it in both projects. Prefer a typed shared contract such as:

```json
{
  "node": {...},
  "node_info": {...},
  "session_diagnostics": {...},
  "latency_ms": 123.4,
  "reachable": true
}
```

Add a Manager↔Node contract test that asserts the exact JSON keys consumed by the frontend.

---

#### C-04 — Add/Edit Node settings are silently ignored

**Evidence**

- `ovmanager/backend/node/ops.py:24-44` and `:47-62` pass `tunnel_address`, `protocol`, `ovpn_port`, and `set_new_setting` into `NodeRequests`.
- `ovmanager/backend/node/requests.py:18` accepts `**_` and discards those values; `check_node()` only performs `GET /sync/status` with a JSON body.
- `ovnode/core/routers/router.py:48-59` expects configuration through `POST /sync/config`.

**Impact**

Adding or editing a node can report success while the OVNode keeps its previous OpenVPN endpoint/protocol/template. Generated profiles may contain stale values such as `UPDATE_VIA_PANEL`.

**Fix**

Implement `NodeRequests.update_config()` with `POST /sync/config`, call it only when `set_new_setting` is true, check its result, and persist the node only after the node configuration succeeds. Add tests for add, edit, and rollback-on-failure.

---

#### C-05 — JWT type, refresh rotation, revocation, and browser storage are unsafe

**Evidence**

- `ovmanager/backend/auth/auth.py:205-223` checks `sub` but never requires `payload["type"] == "access"`; a valid refresh token can be used directly as an API bearer token.
- `:182-202` accepts a refresh token and creates a new access token without rotating or revoking the refresh token.
- `revoke_token()` exists at `:52-71`, but no call site was found; logout is client-side only.
- `frontend/src/context/AuthContext.jsx:28-30` stores access and refresh tokens in `localStorage`.
- `frontend/src/services/api.js:29-42` performs refresh independently for every concurrent 401 response.

**Impact**

Any XSS or malicious browser extension can steal long-lived credentials. Refresh tokens remain reusable for up to seven days. Multiple simultaneous 401s can cause refresh races. A refresh token can access protected endpoints directly.

**Fix**

- Require `type=access` in `get_current_user`.
- Use refresh-token rotation with a server-side token family/reuse detector.
- Revoke refresh tokens on logout/password change/role change.
- Prefer secure, `HttpOnly`, `SameSite` cookies for refresh tokens; if the SPA must use bearer storage, reduce exposure and add a strong CSP.
- Implement a single-flight refresh promise in the Axios interceptor.
- Revalidate the user and role server-side for sensitive requests.

---

#### C-06 — Manager user mutation endpoints have IDOR/ownership gaps

**Evidence**

- `ovmanager/backend/routers/users.py:149-166` updates any user UUID without checking ownership for `admin` users.
- `:169-181` changes status without an ownership check.
- `:216-229` deletes any user UUID without an ownership check.
- The codebase contains `backend/auth/authz.py:35-66`, but these routes do not use the ownership dependency.

**Impact**

A regular admin who obtains or guesses another user’s UUID can update, disable, or delete that user. This is inconsistent with `GET /users/`, which filters regular admins to their own users.

**Fix**

Apply one centralized ownership dependency to every read and mutation route. Add tests for admin A attempting to update/delete/download/admin B’s user.

---

#### C-07 — OVNode download endpoint accepts an unvalidated UID for filesystem paths

**Evidence**

- `ovnode/core/routers/router.py:170-179` calls `download_ovpn_file(uid)` without `validate_user_id(uid)`.
- `ovnode/core/service/user_management.py:272-286` passes the UID into `_client_paths()`, which constructs filesystem paths.
- Other user endpoints do validate the ID, so this is an inconsistent bypass.

**Impact**

A caller with the Node API key can submit path-like IDs and cause path traversal attempts, unintended file checks, or unsafe EasyRSA/path operations. Even if some paths are later rejected, this should not be reachable from an authenticated API boundary.

**Fix**

Validate the UID at the router boundary before any path construction. Make `_client_paths()` defensive too, so it refuses anything outside the expected ID regex regardless of caller.

---

#### C-08 — Both root installers have root-level `eval` injection and unsafe credential defaults

**Evidence**

- `ovmanager/install.sh:51-64` and `ovnode/install.sh:46-60` assign prompt/argument values using `eval`.
- `ovmanager/install.sh:614-617` falls back to `DEFAULT_PASS=admin` for noninteractive/partial flag usage.
- `ovmanager/install.sh:448` prints the admin password in the final summary.
- Both installers use `set -uo pipefail` without `set -e`; failed clone/dependency/build steps can continue.

**Impact**

A malicious value entered into a root installer can execute shell commands. A noninteractive Manager install can leave the panel using `admin/admin`. Credentials are exposed in terminal logs and may be exposed through command-line process listings when passed as flags.

**Fix**

- Remove `eval`; assign variables safely or use a `case`/nameref approach with a fixed variable allowlist.
- Refuse empty/default passwords and require a generated password when noninteractive.
- Never print passwords.
- Use `set -Eeuo pipefail`, explicit error handling, and rollback/cleanup traps.
- Prefer a signed/pinned release artifact over pulling mutable `main`.

---

#### C-09 — Manager Docker build/runtime is broken or non-reproducible

**Evidence**

- `ovmanager/Dockerfile:11-26` runs `pip install --no-cache-dir .` immediately after copying only `pyproject.toml`, before copying `backend/`, `bot/`, `main.py`, and `README.md`.
- A local `pip wheel --no-deps .` against the current tree fails during package discovery with: `Multiple top-level packages discovered in a flat-layout: ['bot', 'backend', 'frontend']`.
- The image switches to `appuser`, but `backend/logger.py:7-9` creates `/app/data` at import and `backend/db/engine.py:8` writes the database there. The Dockerfile does not create/chown that directory.
- `backend/config.py:56` defines `DATA_DIR`, but `backend/db/engine.py` and `backend/logger.py` ignore it.

**Impact**

The image build can fail before source is installed. If it builds through a changed environment, the non-root process may be unable to create/write the database and log directory. Native installer data paths and uninstall/backup behavior also diverge from actual storage.

**Fix**

- Add explicit build-system/package configuration or install dependencies from the lockfile without installing the root package.
- Copy required metadata/source in the correct order.
- Create `/app/data`, `chown` it to `appuser`, and test the image as the final user.
- Centralize data paths around `config.DATA_DIR` and use the same path for DB, logs, backups, and global mlogin state.
- Add a Docker smoke test that starts the image and exercises `/health` plus a database write.

---

### P1 / High

#### H-01 — User status API returns success but does not update Manager DB state

`ovmanager/backend/routers/users.py:169-181` calls the nodes and writes an audit event, but never calls `crud.change_user_status()`. The frontend then refreshes `/users/` and sees the old DB status. Separately, `EditUserModal` omits a status field, while `crud.update_user()` treats the default `status=True` as active (`backend/db/crud.py:167-170`), so editing an inactive user can reactivate it unintentionally.

Fix the DB state transition and node synchronization as one explicit workflow. Preserve the user’s current status unless the request intentionally changes it.

#### H-02 — Disable/limit/delete operations are not transactional across nodes

`backend/routers/users.py:158-162` commits Manager state before node synchronization and ignores node results. `backend/node/ops.py:213-226` returns true when at least one node succeeds and no exception occurs, even if another node returns `False`. A user can therefore be deleted from Manager while still present on one or more nodes.

Use an operation/outbox table with per-node status, retry, reconciliation, and a visible partial-failure state. Do not report success until the policy-defined consistency threshold is met.

#### H-03 — URLPATH protection is bypassable and fails open

- `backend/urlpath.py:128-153` explicitly allows unprefixed `/api/`, `/assets/`, `/sub/`, `/health`, and docs paths even when a secret URLPATH is configured.
- `backend/urlpath.py:29-37` returns an empty URLPATH on any DB error; after the cache expires, a database failure can expose the root application.
- `set_urlpath()` returns success and updates memory even when DB persistence fails.

If URLPATH is a defense-in-depth feature, only health should be intentionally public; require the configured prefix for app/API/assets, or document the actual threat model. Fail closed when the configured value cannot be read.

#### H-04 — Subscription path setting does not change the actual route

`backend/routers/sub.py:18` binds the router prefix at import time using `config.SUBSCRIPTION_PATH`. The settings endpoint updates the DB/config at runtime, but the already-registered route remains at the old path. `get_settings()` can report a new path that does not serve requests.

Use a stable route with runtime path validation/redirect logic, or require a restart and make the UI say so. Add an integration test for changing the path and fetching the generated link.

#### H-05 — Bot-token encryption is inconsistent and can leak/break tokens

- `backend/db/crud.py:13-25` uses `BOT_ENCRYPT_KEY`, but `backend/schema/output.py:11-14` uses a different `BOT_TOKEN_ENCRYPTION_KEY` and generates a random key when absent.
- `backend/routers/setting.py:41-52` returns the raw DB `bot_token` field, despite the comment saying it is masked.
- `crud.update_bot_config()` calls `_fernet.encrypt()` even when `_fernet` is `None`; the “plaintext fallback” warning does not match the implementation.

Use one key name and one encryption service, fail startup if encryption is required but missing, never return ciphertext/plaintext to the browser, and implement masked write-only token updates.

#### H-06 — Native data directory, logs, backups, and mlogin state are split/ignored

The installer advertises `/var/lib/ovmanager`, but DB/log/backup/mlogin code uses paths relative to the repository (`backend/db/engine.py:8`, `backend/logger.py:7`, `backend/routers/mlogin.py:27`). Uninstall removes `/var/lib/ovmanager` but can leave the real DB/logs behind. Backups may not cover the data the operator thinks they cover.

Create one `data_dir` helper and use it everywhere. Add a migration/upgrade test for native and Docker layouts.

#### H-07 — Default Node deployment is HTTP and the API key is a bearer secret

- `ovnode/.env.example` contains a known-looking `CHANGE_ME...` API key that passes the current minimum-length check.
- `ovnode/core/config.py:23-29` only validates length.
- `ovnode/core/app.py:43-51` serves CORS broadly and the service binds `0.0.0.0`; `TLS_METHOD=none` is a supported/default path.
- `ovmanager/backend/node/requests.py:18-21` sends the key over HTTP when `use_tls` is false.

Reject placeholders, require TLS or explicitly require a private network, support certificate verification/CA configuration for self-signed nodes, and rotate node keys.

#### H-08 — OVNode API-key rate limiter can be memory-exhausted

`ovnode/core/auth/auth.py:19-33` creates a lock and bucket keyed by the raw caller-supplied API key. An attacker can send many unique invalid keys and grow both dictionaries without a bound or cleanup.

Hash keys, use a bounded/expiring cache, or rate-limit by trusted source/IP at the reverse proxy. Do not retain unbounded attacker-controlled keys in process memory.

#### H-09 — Public subscription URLs are bearer credentials with no revocation/rate limit

`backend/routers/sub.py:97-180` exposes user status, expiry, traffic, node availability, and `.ovpn` download links to anyone holding the UUID URL. There is no separate revocable subscription token, rate limit, or audit trail for downloads.

Use a separate random subscription token stored hashed in the DB, support rotation/revocation, avoid exposing unnecessary usage data, and rate-limit downloads. Treat the URL as a credential in documentation.

#### H-10 — Backup restore is not process-safe and has path/error handling issues

`backend/routers/maintenance.py:121-173` disposes the SQLAlchemy engine and swaps the DB while the running scheduler/API can still open sessions. The server is not stopped or put into a maintenance lock. The server-backup path check uses string prefix matching (`:197-205`), not `Path.is_relative_to()`, and several errors return raw exception text.

Implement a maintenance lock, stop/pause scheduler jobs, validate the DB schema, use `is_relative_to`, rotate/reopen connections, and restart the process after a successful restore.

#### H-11 — Admin/global settings and diagnostics are over-broad

Examples:

- `backend/routers/admins.py:18-23` lets any authenticated role enumerate admins.
- `backend/routers/setting.py:83-135` allows any authenticated user to change timezone, subscription, and bot settings.
- `backend/routers/maintenance.py:239-275` exposes login health/diagnostics without a main-admin or ownership check.
- `backend/routers/activity.py:12-14` returns the full audit feed to any authenticated role.

Confirm the intended operator model and apply `require_main_admin`, `require_admin_or_main`, and ownership checks consistently.

#### H-12 — Node integration treats partial failures as success

`backend/node/ops.py:137-162` and `backend/node/diagnostics.py:110-126` gather node operations but callers generally discard per-node failures. User update/status/delete routes return success even when one or more nodes are unreachable or reject the operation.

Return per-node results, persist an operation state, retry asynchronously, and show partial failure in the UI.

---

### P2 / Medium and quality risks

#### M-01 — Frontend reset-usage action calls a non-existent/wrong endpoint

`frontend/src/pages/UserManagement.jsx:194-207` calls `GET /users/{uuid}` for “reset usage”. The backend exposes `POST /users/{uuid}/reset-usage` at `backend/routers/users.py:105-115`. The UI action will fail or hit the wrong route.

#### M-02 — Backup tab GET creates a backup instead of listing backups

`frontend/src/pages/Settings/BackupTab.jsx:14-26` calls `GET /maintenance/backup`, but the backend’s GET route creates a backup (`backend/routers/maintenance.py:32-77`). The list route is `/maintenance/backup/list`. Opening the Settings tab can create backups repeatedly and the UI does not reliably populate the list.

#### M-03 — Excessive polling and per-request node fan-out

`GET /users/` invokes `get_active_connection_counts()` across all active nodes. The Dashboard loads users/nodes/security and then separately polls every node; `DashboardLayout` repeats a similar notification fan-out every 30 seconds. This multiplies load as node count grows and can exhaust the threadpool when nodes are slow.

Add a cached server-side snapshot, bounded concurrency, stale-while-revalidate data, and a single dashboard summary endpoint.

#### M-04 — Download-all configs are unbounded and held in memory

`backend/node/ops.py:184-210` loops through every user, performs sequential node calls, and builds a `BytesIO` ZIP in memory. Large deployments can tie up a worker or exhaust memory. Stream or queue the job, cap size/count, and report missing configs.

#### M-05 — NodeRequests URL/TLS handling is fragile

`backend/node/requests.py:18-24` blindly appends `:{port}` to `address`, which breaks addresses that already contain a scheme/port and some IPv6 forms. TLS uses the default certificate verification with no configured CA path, so self-signed Node deployments fail unless certificates are globally trusted.

Normalize endpoints with `urllib.parse`, store host/port/scheme separately, and expose explicit CA/verification settings.

#### M-06 — Manager frontend/API error and response assumptions are brittle

Several UI components assume one response shape, but the backend sometimes returns a different shape or a `success=false` envelope with HTTP 200. Prefer meaningful HTTP status codes and shared TypeScript/OpenAPI-generated types. Add request cancellation on unmount to avoid stale state updates.

#### M-07 — Frontend dependency audit is currently red

The current install reports **20 vulnerabilities: 1 low, 5 moderate, 13 high, 1 critical**. Direct versions include `axios@1.12.2`, `react-router-dom@7.9.4`, `vite@7.1.11`, and `vitest@2.1.9`. Run the audit in CI as a triage gate, update the lockfile, and verify compatibility before release.

#### M-08 — Security headers are incomplete

Manager adds HSTS even without checking request scheme (`backend/app.py:26`), but neither app provides a Content-Security-Policy. Add CSP compatible with the SPA, correct HSTS behavior for TLS/proxy deployments, `Cache-Control: no-store` on credential/config responses, and a trusted-host policy.

#### M-09 — Startup failures are swallowed

`backend/app.py:255-264` logs migration errors and starts the service anyway. `start_bot()` suppresses stdout/stderr and launches a detached subprocess from the `backend` directory, which is unlikely to find the sibling `bot` package and can leave orphaned duplicate bots after restarts.

Use a lifespan-managed scheduler/bot task, fail readiness on migration failure, log startup errors, and supervise child processes.

#### M-10 — CI security gates are non-blocking and one scan targets a missing image

`build.yml` uses `pip-audit || true`, `npm audit || true`, and Trivy `exit-code: '0'`; it also scans `ovmanager:latest` without building that image in the job. Vulnerabilities will not block releases. Build the exact image, scan it, and define an explicit exception workflow with expiry dates.

#### M-11 — Compose is not standalone

`docker-compose.yml` references `./OVNode` and `./OVNode2`, but a fresh OVManager clone does not contain those directories or submodules. The documented compose deployment therefore fails unless the operator manually supplies sibling repositories.

Use explicit submodules, image references, or a documented multi-repo checkout.

#### M-12 — Test coverage misses the risky paths

Current frontend tests cover only `settingsHelpers` (11 tests). Backend tests are smoke/auth-gate tests and do not cover the Manager↔Node contract, ownership matrix, token types/rotation, revocation, disable/reconnect behavior, traffic accounting, Docker permissions, backup restore, or installer failure paths.

Add contract tests, security regression tests, a disposable OpenVPN integration environment, and Docker/installer smoke tests.

---

## Cross-project contract matrix

| Contract | Current state | Result |
|---|---|---|
| Manager health → Node `GET /sync/health` | Compatible | Good |
| Manager status → Node `GET /sync/status` | Transport works; response keys are renamed before frontend use | Dashboard false negatives |
| Manager sessions → Node `GET /sync/sessions` | Compatible in principle | Needs bounded/clamped hours and contract tests |
| Manager traffic → Node `GET /sync/usage` | Manager currently calls `/sync/status` instead | Traffic accounting broken |
| Manager Node settings → Node `POST /sync/config` | No client method/call | Settings silently ignored |
| Manager user create/status/delete → Node | Endpoints exist, but state/result handling is not transactional | Divergence on partial failure |
| Manager disable/delete → OpenVPN enforcement | CCD/revoke code exists; CRL/connection denial is incomplete | Existing certificates can remain usable |
| Manager frontend status fields | Expects `node_info`/`session_diagnostics` | Backend returns `info`/`sessions` |

---

## What is already good

- Node API keys and Manager passwords use constant-time comparisons in the primary paths.
- Password hashing uses bcrypt through Passlib.
- OVNode validates client names and user IDs before most filesystem/EasyRSA operations.
- Management-socket CN input is validated before issuing a kill command.
- Most outbound Manager→Node requests have timeouts and use threadpool offloading.
- SQLite has WAL, busy timeout, and foreign-key pragmas configured.
- The frontend currently passes ESLint, build, and its 11 Vitest tests.
- Both repository shell scripts and Python modules pass basic syntax checks in this workspace.
- Backup upload uses filename sanitization and SQLite validation, although restore lifecycle/authorization still need work.

## Recommended remediation order

### Phase 0 — before public exposure

1. Fix CRL verification, disable/delete enforcement, and add OpenVPN integration tests.
2. Fix Manager↔Node usage/status/config contracts.
3. Fix ownership authorization on every user mutation/read/download path.
4. Enforce access-vs-refresh token types; rotate/revoke refresh tokens; remove long-lived tokens from `localStorage` where possible.
5. Remove installer `eval`, default credentials, password printing, and fail-open error handling.
6. Make the Manager Docker image build and run as its final user; unify `DATA_DIR`.

### Phase 1 — production reliability

7. Add a node-operation outbox/retry/reconciliation model.
8. Fix URLPATH/subscription-path behavior and fail-closed semantics.
9. Fix bot-token encryption and write-only UI behavior.
10. Make backup restore a coordinated maintenance operation.
11. Require TLS/private networking for Node API keys and reject placeholders.
12. Fix frontend reset/backup endpoint bugs.

### Phase 2 — scale and maintainability

13. Add a cached operational snapshot endpoint and bounded polling.
14. Generate shared client types from OpenAPI or maintain contract schemas in tests.
15. Upgrade vulnerable npm dependencies and make CI security checks blocking.
16. Add full integration, Docker, installer, and mobile frontend tests.

## Validation performed in this workspace

- Frontend `npm run lint`: passed.
- Frontend `npm test -- --run`: passed, 11 tests.
- Manager `python -m compileall -q backend`: passed.
- OVNode `python -m compileall -q core`: passed.
- Manager and OVNode installer/hooks: `bash -n` passed.
- `npm audit`: 20 current lockfile vulnerabilities reported.
- Full Python pytest suites were not executed in this sandbox because FastAPI and the project Python dependencies are not installed in the base environment.
