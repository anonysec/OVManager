# Changelog

## 2.1.1 — 2026-09-17

- Installer: Express no longer exits right after the password prompt
  (`set -e` trap); passwords now echo as `*` while typing. Related
  non-fatal returns in `backup`/`update` no longer abort the run.
- Installer: same-server node registration tolerated a duplicated response
  body (it reported failure even though the node was added) and now falls
  back to checking the node list; the frontend build no longer leaves the
  installer in `frontend/`.
- Installer: uninstall asks "Also delete data and backups?" (default No);
  the TUI entry is "Backup" plus a new "Auto backup (host timer)".
- Automatic backups: new settings (Settings → Advanced → Backup), off by
  default — daily time + how many to keep; and a host timer via
  `ovmanager auto-backup on|off|status [--time HH:MM] [--keep N]`.
  `backup --keep N` prunes `/var/backups`.
- Default node name is `ovnode` (was `node-1`).

## 2.1.0 — 2026-09-17

The "clean, fast, beginner-friendly" release tracked in `docs/ROADMAP.md`.

**Highlights**

- **Reliability first** (Step 1): race-safe traffic billing, safe backup
  restore, correct login lockout behind proxies, session revocation on
  password change, expiry/quota activation guards, proper 404s.
- **Simple installers** (Step 2): Express/Custom/Update/Uninstall menus,
  TLS always on (self-signed default, Let's Encrypt domain/IP, custom),
  optional same-server node with automatic registration, and the
  `ovmanager` / `ovm` terminal menu (status, service, logs, backup, update,
  TLS, recovery).
- **Full redesign** (Step 3): Home · Users · Nodes · Health · Settings,
  simplified Users flows, node actions (DNS, IPv6, extra ports, restart,
  self-update), Admins lifecycle + sessions, Audit filters, first-login
  wizard, restyled customer subscription page, fa/ru/cn translated.
- **Speed & light** (Step 4): one DB write per traffic tick, bounded node
  fan-outs, venv-only runtime image, 300-user scale test.
- **Modern touches** (Step 5): minimal installable PWA with a cert-aware
  hint, update checker + one-click panel update, daily Telegram alerts for
  expiry/traffic, button-first Telegram bot, owner password recovery.

**Step 1 — reliability/security batch**

- Billing races: the traffic collector writes with conditional updates
  (expected `used`/`node_usage`) so a concurrent reset or delete wins; one
  commit per tick; the daily-history row is written only with its user row.
- Migrations run numbered steps on adopted databases again (node keys are
  encrypted as intended; future data fixes are never skipped), clean orphan
  daily rows, and add lookup indices.
- Restore: writes get 503 while the swap runs, stale `-wal`/`-shm` are
  removed, the restored database is migrated and verified before success,
  and a failed post-restore check rolls back to the pre-restore copy.
- Login lockout cannot be bypassed with a spoofed `X-Forwarded-For`
  (rightmost hop only, validated IP); `X-Forwarded-Proto` likewise.
- Admin password changes end that admin's live sessions.
- An expired/out-of-quota user cannot be re-activated through the status
  endpoint (same guard as the edit form).
- Audit writes are best-effort: a failed insert no longer turns a completed
  action into a 500.
- Wrong addresses under a secret URLPATH return an empty 404 (was an
  unusual empty 200); `/health` reports the version to loopback only.
- Node names must be unique (prevents cross-billed traffic baselines).
- Geolocation and database backup/restore run off the event loop; the
  all-configs ZIP spools to disk instead of memory.
- Installer keeps TLS private keys 600 (owned by the container uid for
  Docker); installer test updated.

- Installers (Step 2): bare interactive runs open a menu —
  Express / Custom / Update / Uninstall. Express asks only for the admin
  password and uses safe defaults; Custom keeps the full wizard.
- TLS is always on: self-signed by default, Let's Encrypt for a domain or
  an IP, or custom key/cert. `--tls-none` is rejected with a clear message.
- At the end of an install the panel offers to add a VPN node on the same
  server (default No, "not recommended for production"). Express registers
  it in the panel automatically; Custom asks first, otherwise prints the
  name/address/API key. The separate OVNode installer is downloaded
  (fork-aware via `OVNODE_REPO`).
- Source re-downloads on update use `mktemp` instead of a fixed `/tmp` path.

- Redesign wave 1 (Step 3): admin lifecycle — enable/disable (disable revokes
  sessions), per-admin session list + "sign out all devices"; disabled admins
  cannot log in and live sessions are rejected. New `GET /api/health/overview`
  (panel/DB/nodes/TLS/disk/backups with plain-English hints) and
  `GET /api/health/setup`; new Health page in the panel. First design-system
  tokens + UI primitives, nav is Home · Users · Nodes · Health · Settings
  (Admins/Audit under Advanced). Per-node DNS management
  (`PUT /api/nodes/{id}/dns`) and node software update trigger
  (`POST /api/nodes/{id}/update`).
- Redesign wave 2 (Step 3): new Login page, Home dashboard (stat tiles,
  node-health card, expiring-soon and top-talkers), redesigned Users list,
  create/edit form and user detail view — all built on the wave-1 primitives.
- Node management adds a **Restart VPN** action and a runtime **IPv6 on/off**
  toggle (with prefix), alongside the DNS and update triggers; every action
  reports what the node answered.
- Telegram bot is now button-first: persistent Users / Create / Stats / Nodes
  / Settings keyboard, inline user actions (extend, traffic, reset, disable,
  disconnect, delete with confirm, config link) and an owner-only Settings
  screen; typing only for names and values.
- Redesign wave 3: Nodes page + drawer (Overview / Settings / Actions /
  Logs) with DNS, IPv6, extra-ports, restart and self-update actions;
  Settings split into Simple/Advanced; Admins page with enable/disable and
  per-admin session control; Audit filters and relative times; first-login
  setup wizard (Home banner, `/setup`); customer subscription page restyled;
  fa/ru/cn translations completed (0 missing keys); dead dashboard
  components and CSS removed.
- Panel TLS management: `GET /api/tls/status`, `POST /api/tls/upload`,
  `/self-signed`, `/renew` (Let's Encrypt via acme.sh, with host-side
  guidance when unavailable) and `/restart`; managed certs under
  `DATA_DIR/tls/` take precedence on the next start.
- Panel-managed extra VPN ports (`PUT /api/nodes/{id}/ports`) with client
  template failover remotes and native NAT re-apply on the node.
- Speed/light: node fan-outs bounded by a shared semaphore (20) and the
  enforce sweep loads the node list once; panel runtime image ships only the
  built venv (no uv/pip toolchain); 300-user scale test added.
- Minimal PWA: manifest + icons + a versioned service worker that caches
  only the static shell (API/auth/subscription/health are never cached), and
  an "Install app" hint that hides itself while the certificate is
  self-signed. The backend serves `manifest.webmanifest`, `sw.js` and
  `/icons/` with `no-cache` so updates land immediately.
- Update checker + one-click panel update (owner): GitHub check that fails
  soft and caches for an hour, `POST /api/updater/run` running the installer
  detached on native installs (Docker gets the host command); banner on the
  Health page and a version row in Settings → System.
- Telegram alerts: a daily panel job sends one summary for users expiring
  within 3 days and users out of traffic; new Settings toggles
  (`notify_expiry`, `notify_traffic`, migration v6) with an Alerts card.
- Owner password recovery: `install.sh reset-password [--admin-pass ...]`
  edits only `ADMIN_PASSWORD` in `.env`, restarts the panel and waits for
  health; documented in troubleshooting + README.
- Terminal menu (TUI): installs `ovmanager` (+ `ovm` alias) to
  /usr/local/bin — Status, Start/Stop/Restart, Logs, Backup, Update, TLS,
  Recovery (URL/login, owner password, URL path) and Uninstall, with boxed
  `whiptail` dialogs when present and the colored menu otherwise. Every item
  is also a subcommand for scripts (`logs -f`, stable exit codes).
- Hardened the interactive-prompt guard: an unopenable `/dev/tty` now takes
  the non-interactive path instead of silently accepting defaults, and
  `menu` without a terminal exits 2. `fetch_source` uses `mktemp` (last
  fixed `/tmp` path).

**Gap-closure pass**

- Admins now see a **"My activity"** card in Settings (their own recent
  actions; the owner sees theirs).
- A self-signed node's first unverified-TLS fallback writes a
  `node.tls_unverified` audit row (once per node), and SECURITY.md explains
  the risk and mitigations.
- `ovmanager status` / `ovm status` work without root (mutations still
  require it).
- Node drawer gains **Renew server certificate** (owner-only): asks the node
  to re-issue its OpenVPN server certificate via easyrsa, restarts OpenVPN
  and reports the new expiry. Audited as `node.renew_cert`.
- Added `docs/how-it-works.md` (plain-words architecture) and removed the
  last dead CSS blocks plus unused React imports.

## 2.0.2 — 2026-09-07

Panel `2.x` requires node `>= 2.0`.

- Billing: lifetime totals (short sessions/tails/offline counted, resets
  rebaseline); dashed names bill exactly; reset fans out to nodes; delete
  cleans daily rows. Enforce on traffic ticks; 80%/over-quota bell+strip
  warnings + pref; history daily table, 14d graph, top-5/7d, 90d prune.
- Logs: node Logs tab (proxy+validated client), panel rotation/stdout/
  format + docker caps, flap-aware RPC logging, hook ip/pool on decisions,
  node 401/429 client IP, audit widened (node/admin/login-fail/lockout) +
  `?action=` filter.
- UI+geo: plain-HTTP country lookup + retry + validation, manual override
  dropdown, stored-code-only display; lists unified; settings Activity +
  Maintenance pages removed (backup stays); modals one size + sectioned;
  dashboard redesigned (stat strip, underline tabs, flat alerts).
- Sync: clean-stale clears dead markers beside live sessions; no-op PUT
  audited, same PID.
- Removed: onboarding checklist + 42 dead i18n keys; dead stale alert
  toggle + retired registry shim; `Dashboard.css.bak` era CSS already gone.
- Fix: Telegram bot disabled (no token / toggled off) no longer WARNINGs
  every minute — INFO once, retry hourly; crashes still warn+restart.

## 2.0.1 — 2026-09-05

- Tests: multi-node failure degradation (dead node, real refused sockets).
- Perf: single shared `/server/settings` load for 4 sections (was 4,
  vision-verified pixel-identical).
- Docs: badges, compat matrix, acceptable-use note, `OVM_REPO` fork override.

## 2.0.0 — 2026-09-05

Panel `2.x` requires node `>= 2.0`.

**Public release.** License is MIT (was proprietary). Install Docker-fresh
with `install.sh -y --mode docker`, add the node bundle, done.

- Users API: DB-level `?search=` + pagination (bot no longer pulls the
  table per keystroke); create without `expiry_date` falls back to
  `Settings.default_days`; `DELETE` is best-effort and names unreachable
  nodes; NULL-expiry extend anchors on today.
- Sync: limit pushes skip offline nodes and unchanged pairs (failures stay
  dirty); metrics/health derive counts from one sessions poll (was two);
  audit logs pruned after 90 days.
- Auth: in-memory-only login rate-limit (5 strikes → 429); dead global
  login registry retired (~180 lines removed, shapes unchanged).
- Deletes: `Dashboard.css.bak`, `GET /metrics/stream` (chart polls;
  `/live/stream` is the single SSE), standalone `bot/` packaging files.
- Frontend: Add/Edit User/Admin/Node modals unified into `*FormModal`;
  `Settings.jsx` split into `pages/settings/` modules (pure motion);
  onboarding lazy-loads only when not dismissed; i18n drift gate
  (`npm run check:i18n`, also in CI); 42 dead CSS rules removed
  (vision-verified, pixel-identical).
- Installer: dry-run/guard paths work without root; Docker mode writes
  container `DATA_DIR`, owns the host dir, readable TLS certs, clean
  `--json` stdout. Panel talks self-signed nodes (verified-first TLS
  with one warned retry, incl. `.ovpn` downloads).
- Tests: backup/restore round-trip, traffic accounting (no double-count),
  lockout/429, sync skip/retry, registry retirement, fan-out dedup,
  installer behavior. Suite 120+ green, ruff clean, zero CI warnings.

## 1.6.0

- Pre-freeze state: opaque sessions, encrypted node/bot keys, URL-path
  stealth, single-poller live collector, Telegram bot (4 locales).
