# Changelog

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
