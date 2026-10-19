# Backend Security + Correctness Sweep — Findings

Scope: `cmd/`, `internal/{auth,billing,cli,db,health,node,notify,panel,telemetry,users,version,webfs}`, `test/`. Read-only inspection; nothing modified.

Format: `- [sev][file:line] claim — evidence — fix`. Max 20 rules; nits as separate bullets. Ends with the 10-minute triage.

---

## Rules

- [CRITICAL][panel.go:138-140] `MountSub` registers `subStaticJS`/`subDownload`/`subPage` with **no auth wrapper** — serves OVPN client configs and per-user subscription data to anyone who can reach the subscription path; `subUser` (sub.go:280) keys purely on UUID with no session check — evidence: `mux.HandleFunc("GET "+prefix+"/download/{uuid}/{node_name}", h.subDownload)` and `mux.HandleFunc("GET "+prefix+"/{uuid}", h.subPage)` register bare handlers (panel.go:138-140), and `subUser` runs `SELECT ... FROM users WHERE uuid = ?` with no `CurrentUser`/`RequireUser` gate (sub.go:286-288) — fix: wrap all three routes with `h.Svc.RequireUser` (download: `RequireOwner`) or add a session check inside `subUser`.

- [HIGH][panel.go:58-59] `GET /health/setup` and `GET /health/tls` use `user()` instead of `owner()` — exposes server settings/health to any authenticated user while every sibling `/health/*` route requires owner — evidence: `mux.HandleFunc("GET /health/setup", user(h.healthSetup))` and `mux.HandleFunc("GET /health/tls", user(h.healthTLS))` (panel.go:58-59) vs `owner(h.healthOverview)` at line 55 — fix: switch both to `owner(h.*)` unless user-level intent is documented.

- [HIGH][auth/handler.go:148-169] No CSRF / Referer / Origin validation anywhere in `internal/` — every state-changing POST (`/maintenance/*`, `/tls/*`, `/updater/*`, `/server/*`, db backup/restore) accepts cross-origin form posts protected only by the bearer/session cookie — evidence: grep for CSRF/Referer/Origin across `internal/` returns only `SameSite: http.SameSiteLaxMode` (auth/handler.go:97); all `owner(...)` POST registrations in panel.go:73-108,125 lack any origin check — fix: add a per-session CSRF token or require `Origin`/`Referer` to match the panel host on mutating endpoints.

- [HIGH][telemetry/handler.go:396-408] `CollectMetrics` performs unchecked type asserts on node-sourced data (the `ok` is discarded) — a malformed node payload can panic the live-snapshot collector — evidence: `live, _ := sessions["live_sessions"].([]any)` and `sess, _ := item.(map[string]any)` with `_, _` discarding the type-assert ok (handler.go:398-400) — fix: assert with ok-checks or a type-switch and skip/record bad frames instead of panicking.

- [MEDIUM][db/migrate.go:808-848] All node keys decrypt under **one global key** (`NODE_ENCRYPT_KEY` falling back to `BOT_KEY`) and are then stored **plaintext** after migration — one key compromise exposes every node key — evidence: `nodeKey = botKey` fallback (migrate.go:809-811) and `UPDATE nodes SET key = ? WHERE id = ?` writing plaintext (migrate.go:844) — fix: per-node key wrapping (or HSM-bound wrapping), rotate the wrapping key on compromise, never persist plaintext node keys.

- [MEDIUM][node/client.go:171,265,663] Node client uses `InsecureSkipVerify: true` TLS fallback paths — MITM on the panel→node control channel when pin verification fails — evidence: `InsecureSkipVerify: true //nolint:gosec` (client.go:171), a second `http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}` (client.go:265), and `do(&tls.Config{InsecureSkipVerify: true})` fallback (client.go:663) — fix: remove insecure fallbacks, require pinned/verified peer certificate only.

- [MEDIUM][telemetry/stream.go:211] `StreamHandler` does an inline `CurrentUser` check instead of the `RequireUser`/`RequireOwner` wrapper — protected but pattern-inconsistent; a future added SSE route could skip the check — evidence: `if _, ok := svc.CurrentUser(r); !ok { ... 401 ... }` (stream.go:211-214) vs the wrapper pattern in auth/handler.go:148-169 — fix: route `/live/stream` through the same wrapper used by `Mount`.

- [LOW][auth/handler.go:86-98] Session cookie `Secure` flag is conditional on `r.TLS` — over plain HTTP or mis-terminated TLS the `ovm_session` cookie travels without `Secure`, enabling session hijack — evidence: `secure := r.TLS != nil` then `Secure: secure` (auth/handler.go:86-97) — fix: force `Secure=true` when behind `TrustedProxy`/HTTPS, or serve only over TLS.

- [LOW][install.sh:96-99] Installer is delivered as `curl|bash` of a remote script (with a sha256 sidecar check) — remote code execution vector at install time if the release host is compromised — evidence: `curl -fsSL -o "$work/$asset.sha256" ...` then `sha256sum -c` (install.sh:96-99) — fix: keep checksum verification, add a detached signature and a static binary/air-gapped install path.

- [LOW][panel/sub.go:229-252] `subDownload` serves node OVPN configs keyed solely by a subscription UUID (a bearer link) — possession of a valid subscription link yields a client config with no caller identity — evidence: `user, ok := h.subUser(w, r.PathValue("uuid"), r)` then `node.DownloadOVPNClient(...)` with no session/identity check beyond the UUID (sub.go:234-244) — fix: this is intended link-based delivery; pair with route-level auth (#1) so the link is the only secret, and keep the existing per-IP rate limit.

---

## Nits (verified safe, no fix required unless behavior changes)

- `setColumns` builds a dynamic column name from internal keys only (panel.go:369) — allowlisted, user input never reaches the column position.
- `cleanupCandidates` string-concats a WHERE clause from a hardcoded table/column list (maintenance.go:550-559) — safe; do not interpolate user input.
- Telemetry `DELETE` targets a hardcoded table list (telemetry/handler.go:431) — safe; no user-controlled table names.
- No hardcoded secrets found; logs do not print key material; no `pprof`/debug/metrics public endpoint; `go.mod` pins `modernc.org/sqlite v1.60.1` with no `replace` directives — maintain this posture.

---

Top 3 things if I only had 10 minutes, ranked by risk×effort:
1. **Add the auth wrapper to `MountSub` routes** (panel.go:138-140) — CRITICAL risk, trivial effort: one `RequireUser`/`RequireOwner` wrapper per route stops unauthenticated OVPN config and subscription-data exposure.
2. **Guard the type asserts in `CollectMetrics`** (telemetry/handler.go:398-400) — HIGH risk, low effort: ok-checks/type-switch prevent a malformed node payload from panicking the live-snapshot collector.
3. **Add CSRF/Origin protection on mutating POSTs** (panel.go:73-108, auth/handler.go:148-169) — HIGH risk, medium effort: a per-session token or `Origin`/`Referer` match closes cross-origin state-changing attacks across every maintenance/TLS/updater/db endpoint.
