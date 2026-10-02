# Changelog

## 1.0.3 — 2026-10-02

The screen clears, and the output uses your terminal.

**Fixed**

- The screen never cleared. `render_screen` ran `command clear >/dev/null 2>&1`,
  and `clear` clears by *printing* escape codes — so the redirection threw them
  away. The fallback only ran when `clear` failed, which it does not, making the
  function a no-op that looked like it worked. Both start-screen clears had it.
- The menu printed its prompt twice whenever the 2-second keystroke read timed
  out, because the fallback called `ask()`, which prints the same prompt again.
- The rule was a hardcoded 46 characters. It is now the terminal's width, from
  `tput`, then `stty`, then `COLUMNS`, clamped to [48, 100]. A pipe still gets
  80.

All three were found by running the installer on a real pty. None of them is
reachable from a pipe, which is where the tests live.

908 pass.

## 1.0.2 — 2026-10-02

The bot moves under the backend, and lint lives in one place.

**Layout**

`bot/` is now `backend/bot/`. The bot already imported `backend.urlpath`,
`backend.db`, `backend.config` and `backend.validation`, and
`backend/bot_supervisor.py` already owned its process, so this makes an existing
one-way dependency explicit. Verified in the built image: `backend.bot.main`
imports, `/app/bot` is gone, and the supervisor launches the new module.

**CI**

Both workflows listed the lint targets as well as the Makefile did, so a path
change had to be made twice — and CI failed twice while the local run passed.
They now call `make lint-backend`, split from `lint-frontend` so each job runs
the half it can actually check. pyright resolves against the project venv.

908 pass.

## 1.0.1 — 2026-10-01

One renderer for every character, and a CLI that matches it.

**Output**

- `ovm doctor` is one line when clean and a failure-first list when not, with each
  fix in its label's own column. It was fifteen lines of `ok`.
- A clean `ovm` is 27 lines, down from 64. `Service account` — fifteen characters,
  and the label on the check most likely to fail — lines up because the column is
  computed from the labels actually present.
- The installer and the CLI share one renderer. `scripts/lib/render.sh` is
  byte-identical to the node's, and a test enforces it.

**A bare install is interactive**

The node installer read a missing terminal as "no questions wanted" and installed
anyway, reporting success for choices nobody made. A script that lost its tty —
CI, a cron job, a pipeline — got a complete install. A bare run is now
interactive unconditionally and stops without a terminal, naming `-y`. Bad input
is still reported as bad input, not as a complaint about the terminal.

**Fixed**

- A successful install exited non-zero: the Ready card interpolated a function as
  a variable, fatal under `set -u` on its last line, after the panel was serving.
- `ovm backup` wrote nothing — an unguarded `$1` after `shift`.
- `ovm backup schedule` did nothing and exited 0 — `shift 2` on one argument.
- `ovm doctor --all` changed nothing: the flag parsed and was dropped.
- Eleven places told an operator to run a name the tool no longer advertises.

**Suite**

175s → 71s, and a 22s `make check` for the inner loop. Two broken tests were a
third of the runtime. 908 pass.

**Layout**

`site/` and `docs/` moved under `.github/`, and `.claude/` is ignored and
untracked.

## 1.0.0 — 2026-09-29 — 2026-09-29

First public release.

**Install**

- One installer for both modes: native (systemd) or Docker, with safe defaults
  and no questions.
- Three flags, `-y/--yes`, `--docker` and `-h/--help`. Everything else is an
  `OVM_*` variable, so a scripted install and a wizard install produce the same
  configuration. Older spellings still work and say what replaces them.
- Installs a verified release archive and checks its published checksum. Nothing
  is built on your server.
- TLS is always on: self-signed by default, Let's Encrypt or your own
  certificate if you prefer. The self-signed browser warning is named in the
  summary rather than hidden.

**First login**

- The installer mints no owner password. It prints a one-time claim key, and you
  open the printed URL and choose the password in the browser.
- The password is stored as a bcrypt hash in the panel database, never in `.env`.
- The key is single-use and rate-limited. Lost it before claiming?
  `ovm owner-claim` prints a new one.

**The panel**

- Users with a traffic quota, an expiry date and a device limit that holds at
  connect time, on the node.
- Traffic is read from each node's lifetime totals every five minutes and only
  the increase is billed, so restarts and disconnects cannot double-count.
- Subscription links and per-user `.ovpn` downloads.
- Any number of VPN nodes, with live health, session counts and per-node DNS,
  IPv6 and extra ports.
- Backups now, on a schedule, off-site over SSH, or into Telegram. Restores are
  atomic and keep the previous database as a fallback.
- A secret URL prefix for the panel, an audit log, extra admin accounts, and a
  Telegram bot (off by default). Available in English, Persian, Russian and
  Chinese.

**Managing it**

- `ovm status`, `ovm doctor [--fix]`, `ovm start|stop|restart`, `ovm logs`,
  `ovm backup`, `ovm restore`, `ovm https`, `ovm tls-status`, `ovm recovery`,
  `ovm update`, `ovm rollback`, `ovm recover-update`, `ovm reset-password`,
  `ovm reset-urlpath`, `ovm owner-claim`, `ovm completion`, `ovm version-script`,
  `ovm uninstall [--purge]`.
- Updates download and verify the release, stage it, and roll back automatically
  if the new version does not come up. The database migrates on the next start.
- Uninstall keeps your data. `--purge` takes a snapshot first, then deletes it.
