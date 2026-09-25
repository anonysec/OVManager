# Changelog

## Unreleased

Structure pass (no behavior change) plus one owner decision: secrets are
no longer encrypted at rest. The server itself — owner login and the
0600 database file — is the trust boundary, so there is no second secret
to keep or rotate (same model as PasarGuard):

- New migration decrypts legacy `enc:` bot tokens and node keys once on
  first boot, using the retired `BOT/NODE_ENCRYPT_KEY` values still in
  `.env` on upgrade. Rows that cannot be decrypted are left as-is with a
  warning (re-save the token/key). Schema version 13 → 14.
- `BOT_ENCRYPT_KEY`, `NODE_ENCRYPT_KEY` and `BACKUP_ENCRYPT_KEY` are
  deprecated no-ops — safe to delete from `.env`. The installer no
  longer generates any of them.
- Code organization: `backend/app.py` split into middlewares, scheduler
  and bot-supervisor modules; `backend/db/crud.py` split per entity;
  telemetry routers merged; shared input validators (username, urlpath,
  domain, email) defined once and used by both API and bot; Telegram bot
  gained a callback registry and conversation-flow helpers. All import
  paths keep working.

## 1.0.4 — 2026-09-25

Fixes the 1.0.3 upgrade path: updates are staged by the *old*
installer, so its `.env` copy still carries `BACKUP_ENCRYPT_KEY` and
the new backend refused to boot (failover worked, nothing updated).
The retired key is now a deprecated no-op field, pinned by a
regression test that boots with a key-era `.env`. v1.0.3 remains
valid for fresh installs.

## 1.0.3 — 2026-09-25

Backup key removed; backups go plain. The server itself is the trust
boundary (owner-only API, SSH for terminal), so there is no second
secret to manage:

- No `BACKUP_ENCRYPT_KEY` generation, storage, validation or display.
  Telegram copies are the verified bundle as-is.
- Updates scrub the retired key from the staged `.env` so the new
  backend (which rejects unknown keys) boots first try.
- `tls.restart` no longer builds a shell string; fixed argv only.
- Abuse-surface regression tests: offsite-target metacharacters,
  restore-upload traversal, malicious TLS domains (never executed),
  bundle member allowlist, shell-free spawn.

Owner note: copies sent encrypted by earlier releases can no longer be
read back by this build — keep the old key only if such copies exist.

## 1.0.2 — 2026-09-25

Owner-reviewed UX and behavior batch, validated live:

- Fresh installs seed an owner row (Admins is never empty), one active
  user, and a `panel.first_run` audit entry visible in Activity.
- New-user defaults resolve per admin over the owner global
  (Settings → Defaults): the Add User form, the API and the Telegram
  bot's Standard plan all use the creating admin's effective plan.
- Connection events are split by meaning: real TLS/auth failures
  (danger) vs policy rejects like disabled users and device limits
  (informational), each with node, user, timestamp and ongoing status.
  The notification bell only raises danger for real failures.
- Users page: debounced search, capped/collapsible label chips with
  truncation, styled label input.
- Settings is one flow (no Simple/Advanced split); dashboard polling
  runs on a fixed cadence with no refresh setting; node creation is
  always TLS; the setup wizard dismisses itself when done; the
  Install-app hint links to TLS settings.
- Test-hygiene fix: sandboxed installer tests can no longer overwrite
  the live systemd unit (this bit the live panel once during validation).
- Dead code removed across backend, bot and frontend (-1150 lines).

Pairs with OVNode 1.0.0 (unchanged this round: +3 diagnostic fixes
already live — reject classification, strict max-login line, observed
TLS timestamps).

## 1.0.1 — 2026-09-24

Fresh-install fixes found by validating the frozen 1.0.0 baseline on a
real host:

- A backtick inside the unquoted systemd UNIT heredoc executed `ovm stop`
  on every fresh install (surfaced as "ovm: command not found"). It is
  now a plain comment, with a regression test that rejects unescaped
  backticks in any unquoted heredoc.
- Native installs now set UMask=0077, so the panel database, WAL and logs
  are private from the first byte instead of world-readable until
  `ovm doctor --fix` corrected them.

Verified live: clean install log with zero warnings, database 0600, doctor
reports healthy with no manual fix.

## 1.0.0 — frozen baseline (superseded by 1.0.1)

Version reset: pre-publish cleanup. History was rewritten to a single
identity, all prior releases/tags removed, numbering restarted at 1.0.0.
Installer-harmony work landed before the first public release.

## 1.2.8 — 2026-09-21

Redesign release (squash of #14 + validated follow-ups from #15):
beginner-first installer (Install / Install with Docker) and manager
TUIs, transactional reboot-safe updates with journals and `recover-update`,
verified `.ovmbak` bundles with optional encrypted Telegram delivery,
unified HTTPS management with rollback, `doctor [--fix]`, operation
locking, owner-only operation status APIs, and legal/privacy documentation.
Validated live: fresh host + Docker installs, update commit + failover,
kill -9 recovery, backup/restore, repair flows. Pairs with OVNode 1.1.6.
