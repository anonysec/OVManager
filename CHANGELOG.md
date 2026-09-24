# Changelog

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
