---
name: ovmanager
description: Use when working in the OVManager repository — the OpenVPN panel (FastAPI + SQLite + React). Verify commands, layout of install.sh / manager.sh / cli, house rules, release flow, and the shell and credential traps this codebase has actually hit.
---

# OVManager (panel)

The panel half of the OVManager/OVNode pair. Node agent: `/root/workspace/OVNode`.
Shared project instructions live in `/root/workspace/CLAUDE.md`; the `ovmanager-dev`
and `ov-release` skills go deeper — this file is the repo-anchored version.

## Verify before claiming done

```bash
.venv/bin/python -m pytest tests/ -q      # filterwarnings = error, so a new warning fails
.venv/bin/ruff check backend bot cli main.py tests scripts/bench
.venv/bin/ruff format --check backend bot cli main.py tests scripts/bench
bash -n install.sh manager.sh scripts/lib/*.sh
cd frontend && npm run verify
```

`make test` / `make lint` / `make verify` wrap exactly these (`lint` = the four above
including `npx eslint src/` and `git diff --check`; `verify` = `lint` + frontend + the
OpenAPI export). `make verify` does **not** run the backend suite — that is `make test`.

`npm run verify` is `build && check:tokens && check:i18n && check:rtl && eslint src/ &&
check:types && vitest run`. CI runs the same chain in three parallel jobs
(`backend`, `frontend`, `frontend-dist`) — see `.github/workflows/ci.yml`.

## Where things live

| Path | What |
|---|---|
| `install.sh` | installer, updater and uninstaller. Fetches `scripts/lib/*.sh` from the `v${VERSION}` tag at runtime, so a version bump must be pushed and released before it can run. |
| `manager.sh` | the `ovm` CLI (installed as `/usr/local/bin/ovm`). |
| `cli/` | the Python operator CLI, `python -m cli.main`. `ovm status`, `doctor`, `tls-status`, `backups`, `restore` and `reset-password` delegate here so there is one implementation. |
| `scripts/lib/` | `common.sh`, `prompt.sh`, `env.sh`, `system.sh`, `backup.sh`, `tls.sh`, `policy.sh` — the only definition of every shared shell helper. |
| `scripts/bench/` | fan-out benchmarks. Not tests: figures depend on core count. |
| `backend/` `bot/` `main.py` | FastAPI app, Telegram bot, entry point. |
| `frontend/` | React 19 + Vite. |
| `tests/test_version_parity.py` | pins every place the version is written. |

## House rules

Full list in `/root/workspace/CLAUDE.md`. The ones a change actually trips over:

- `frontend/src/tokens.css` is the only file allowed to declare `:root` or
  `html[data-theme=...]`; use semantic tokens, never hex.
- All four of `frontend/src/lang/{en,fa,ru,cn}.json` must keep identical key sets.
  Persian is RTL — logical CSS (`margin-inline`, `inset-inline`, `text-align: start`),
  never `margin-left` or `left:`.
- No code comments unless asked; existing ones explain a non-obvious tradeoff.
- The panel is prefix-agnostic (`URLPATH`): never hardcode `/api` paths that bypass
  the prefix helper.
- Traffic accounting stays race-safe — conditional `WHERE used IS :old` updates
  (`backend/operations/daily_checks.py`). It is not a read-then-write to simplify.
- Node HTTP calls go through `backend/node/requests.py` (`node_client(node)`), never
  a raw `requests` call in a router.
- `python-multipart` is required at runtime even though nothing imports it directly.

## Traps this codebase has hit

### A function whose last statement is `[[ … ]] && cmd` returns 1

Under `set -Eeuo pipefail` (both shell entrypoints) that aborts the caller with no
output. Use `if`, and end the function with an explicit `return 0`. Both places this
was actually hit carry a comment: `install.sh:697` and `manager.sh:731`; `install.sh:1434`
adds the deliberate `return 0` for the same reason.

### `${BASH_SOURCE[0]}` is unbound under `set -u` when the script arrives on stdin

The documented one-liner (`curl … | sudo bash -s -- --yes`) leaves it unset, and the
bare `"${BASH_SOURCE[0]}"` was a fatal "unbound variable" — that install never ran.
Always spell it `"${BASH_SOURCE[0]:-}"`. Explained at `install.sh:1544`; the guards are
`install.sh:80` (locating `scripts/lib`) and `install.sh:1547` (run `main` only when
executed, not sourced).

### One definition per shell helper

`scripts/lib/` is the only home for a shared helper; `install.sh` and `manager.sh`
source it, never copy it. `tests/test_lib_sourcing.py` asserts the invariant, and
`install.sh` / `manager.sh` still keep their own `main` / `parse_args` / usage because
those are two programs, not two copies.

### The owner credential is a database row, not `.env`

`admins` row whose `username` matches `ADMIN_USERNAME`. `ADMIN_PASSWORD` is ignored
outright — no code path reads it (`backend/config.py:48` only warns), and
`ADMIN_PASSWORD_HASH` survives solely so the v16 migration can import a pre-upgrade
hash. First run creates the owner with no password; set one with

```bash
.venv/bin/python -m cli.main reset-password --admin-pass 'a-strong-password'
```

The flag spelling differs by entry point: `python -m cli.main` takes `--admin-pass`;
the installed `ovm` takes `-p/--pass` and delegates.

## Releasing

`ov-release` covers the whole checklist. The two things worth repeating:

- Eight version occurrences across seven files, excluding CHANGELOG history:
  `pyproject.toml`, `backend/version.py`, `install.sh`, `manager.sh`,
  `frontend/package.json`, `frontend/package-lock.json` (root `"version"` *and*
  `packages[""].version`), and the README badge — plus a new `CHANGELOG.md` heading.
  `manager.sh` is a real spot: nothing syncs it at install time.
  `tests/test_version_parity.py` asserts all of them, but the list is enumerated, not
  discovered, so a new spot will not be noticed on its own.
- Publish the GitHub release **before** the runtime smoke. `install.sh` downloads the
  release tarball, not the source tree, so an install between push and release fails
  with "No verified release file is available".

This machine is the test VPS: the panel installs to `/opt/ovmanager` on port 2095 as
`ovmanager.service`. Clean up with `install.sh uninstall --purge -y` afterwards.
