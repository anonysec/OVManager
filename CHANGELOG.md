# Changelog

## 1.2.8 — 2026-09-21

Redesign release (squash of #14 + validated follow-ups from #15):
beginner-first installer (Install / Install with Docker) and manager
TUIs, transactional reboot-safe updates with journals and `recover-update`,
verified `.ovmbak` bundles with optional encrypted Telegram delivery,
unified HTTPS management with rollback, `doctor [--fix]`, operation
locking, owner-only operation status APIs, and legal/privacy documentation.
Validated live: fresh host + Docker installs, update commit + failover,
kill -9 recovery, backup/restore, repair flows. Pairs with OVNode 1.1.6.

## 1.2.7 — 2026-09-20

Checksum-mismatch follow-up: release downloads are archive-checked
before the checksum (a redirect stub now fails with a re-bootstrap
hint, never as a checksum mismatch); GitHub Pages bootstrap URL
retired — every one-liner uses raw.githubusercontent.com; stranded
≤1.2.5 boxes get a documented re-bootstrap path. Installer menus
redone: one numbered dialect, wizard/install step counters, shorter
professional copy, plain success card.

## 1.2.6 — 2026-09-20

Follow-up fixes: release downloads follow redirects (`curl -L`),
entry-point executable bits pinned by tests, manager delegates
update/uninstall before the root gate (non-root friendly), and owner/tag
tests no longer assume the owner is named `admin` (fixes CI). CI shares
the frontend build with backend tests; Pages auto-deploy off.

## 1.2.5 — 2026-09-20

Critical fixes over 1.2.4: fresh installs work again (`do_install` ensures
`uv`; `apply_env` no longer trips `set -e` on its last line), and the
`install` word points at the default action instead of a nonexistent
manager command.

## 1.2.4 — 2026-09-20

Fresh rewrite of the shell layer (Concept A): tiny installer with
zero-question defaults, numbered `interactive` wizard, `--version` pins,
code snapshots with automatic update rollback, and plan output by default.
New `ovm doctor` (service, disk, cert, backups) with `--fix`, and
`ovm rollback`. Flags cut to `-y/-j/-h/-p/-v/--purge`; `--pass` replaces
`--admin-pass` (`OVM_PASS`); `--tls` takes 1-4; Pages URLs retired in favor
of raw.githubusercontent.com. Production venv diet (`--no-dev` everywhere,
import/diet gates).

## 1.2.3 — 2026-09-19

Concept-A split: the installer (`install.sh`) only installs, updates and
uninstalls; day-to-day operations move to the manager (`manager.sh`,
installed as `ovmanager`/`ovm`) with a numbered menu. Shared shell code
lives in `lib/common.sh`. Updating auto-swaps the old installer-copy CLI
for the manager. Install flags trimmed (`--tls 1-4`, wizard-first options);
`status`/`logs`/`backup`/`tls`/`recovery` on `install.sh` now redirect to
`ovm`. Prebuilt release tarballs continue (now including the manager).

## 1.2.2 — 2026-09-19

Version reset: the `2.x` release line is retired and the project continues
on the `1.x` line. No code changes in this release — version strings only.
Pairs with OVNode `1.1.0` (same sync API contract).

- `pyproject.toml`, `backend/version.py`, `install.sh`, `frontend/package.json`,
  `frontend/package-lock.json`, `uv.lock` and the README badge now report `1.2.2`.
- All `2.x` GitHub releases, tags and container images are removed; the
  update checker no longer offers them.

## 1.6.0

- Pre-freeze state: opaque sessions, encrypted node/bot keys, URL-path
  stealth, single-poller live collector, Telegram bot (4 locales).
