# Changelog

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
