# OVManager contract spec (condense baseline)

One-page contract for the panel. Phase 2 may delete anything not listed
here; nothing listed here may change behavior.

## Features that survive
- Browser API: users CRUD/audit, nodes management, traffic/billing, settings
  (incl. backup schedule + offsite target), TLS/ACME, backup/restore UI,
  maintenance sweep, telegram/notify hooks, subscription page.
- CLI: service/backup/restore/update/pairing verbs; `runRestore` semantics
  preserved (stop → verify inactivity → swap → ownership repair → restart →
  health; rollback on failure; already-stopped stays stopped; unowned refused).
- Node fan-out: traffic poll, policy reconcile, revocation delivery,
  stale-session cleanup, diagnostics, geolocation.
- DB: schema v29 — `users` AUTOINCREMENT (no ID reuse, seeded incl. deleted
  snapshots), `pending_user_revocations` (PK node+user, no user FK, no
  secrets), `settings_kv` (`backup.last_success_day`, push hashes), daily
  traffic, audit, node health.

## Frozen contracts
- Panel↔node `/sync` client shapes (contract.json): `PUT /sync/user`
  (id,name,max_logins,status), DELETE /sync/user/{uid}, GET /sync/usage
  (`totals`+`totals_epochs`), GET /sync/download/ovpn/{uid}.
- Browser response envelopes (FastAPI shapes: `ResponseModel`, `detail` errors,
  422 validation).
- node_usage bookkeeping keys: `push_hash`, `__epochs`, `__reseed` —
  reserved only in bookkeeping; user named `push_hash` is billed normally.
- Integer precision beyond 2^53 for totals; invalid samples never mutate
  baselines; D5 held baseline.

## Invariants (each has a test)
- Deletion: one transaction creates one job per registered node (incl.
  status=0) + removes account/history; jobs removed only on HTTP success;
  failed jobs retain `last_error` and retry (limit 20/pass, single pass,
  no goroutine per row); delayed job can never hit a new account (IDs
  monotonic).
- Policy: effective access = manual flag AND not (expired OR over quota);
  sweep never re-enables a manually disabled user; hash recorded only on
  acknowledgment; forced full replay ≥ every 10 min; ZIP download pushes
  policy first; update validates max_logins 0..1000 + types before any RPC.
- Accounting: symmetric epoch aggregation; reseed invalidates offline
  epochs; quota/expiry enforced in the same tick as billing.
- Backup: minute ticker, saved settings/timezone read per tick,
  `backup.last_success_day` only after verified snapshot; verify-before-prune();
  offsite bounded (5m, SSH keepalives); local success ≠ offsite success.

## Explicitly out
- Unbounded goroutine-per-job delivery; second expiry/quota rule outside
  `node.AccessBlocked`; raw-DB telegram attachments; manual-backup
  backups inside automatic retention; multi-node fan-out without deadlines.
