# Changelog

## 2.0.0 (unreleased) — freeze + slim

Panel `2.x` requires node `>= 2.0`.

- License: MIT (was proprietary).
- Deletes: `Dashboard.css.bak`, `GET /metrics/stream` (chart polls;
  `/live/stream` is the single SSE), standalone `bot/` packaging files.
- Users API: DB-level `?search=` + pagination; create without `expiry_date`
  falls back to `Settings.default_days`; `DELETE` is best-effort and names
  unreachable nodes instead of failing.
- Sync: limit pushes skip offline nodes; metrics/health derive connection
  counts from one sessions poll (was two); audit logs pruned after 90 days.
- Frontend: Add/Edit User/Admin/Node modals unified into `*FormModal`;
  i18n drift gate (`npm run check:i18n`, also in CI).
- Fixes: NULL-expiry extend anchors on today; `ServerHealth` lint error.

## 1.6.0

- Pre-freeze state: opaque sessions, encrypted node/bot keys, URL-path
  stealth, single-poller live collector, Telegram bot (4 locales).
