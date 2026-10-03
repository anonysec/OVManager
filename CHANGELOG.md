# Changelog

## 1.0.43 — 2026-10-03

The installer works offline, and a restore no longer bricks the panel.

**Fixed**

`ovm restore` left the panel crash-looping on `sqlite3.OperationalError:
unable to open database file`, and the one-line chown that recovers it hides
how much the restore path had been silently corrupting.

The cause is ownership, not the restore. The candidate that gets activated
comes from `mkstemp`, so it belongs to whoever ran the command — root, for
`ovm restore` — and `os.replace` keeps the *candidate's* owner rather than the
live file's. Install-time `chown` put the database on the service account, so
that is the owner the panel needs; the restore threw it away. The file came
back `root:root 0600` while the panel runs as an unprivileged account, and a
database it cannot open is a panel that will not boot.

The owner is captured from the live database before anything is replaced and
re-applied to the activated file. Capturing rather than hardcoding is the
point: the same code is correct for the native service account and for uid
1000 under Docker, which needs no configuration here. The rollback path had
the same defect and gets the same treatment — a restore that fails after
activation used to leave the panel unable to read the file it rolled back to.

The chown is best-effort and warns rather than aborting: under Docker the file
is already uid 1000, and a failure there must not discard a restore that has
already passed its integrity check.

Every install also printed this in the middle of a working download:

    line 472: /tmp/tmp.XXXX/ovmanager-1.0.4.tar.gz: No such file or directory

`fetch_to_file` measures the growing file every 0.4s to drive the progress bar,
and on the first poll curl has not created it yet. The line read

    have="$(wc -c < "$out" 2>/dev/null || printf 0)"

`2>/dev/null` never covered it. Bash applies redirections left to right, so the
input redirect failed first and printed to the real stderr before anything was
redirected. The count was always right — the `|| printf 0` fallback caught it —
so this was noise dressed as a failure, in the one step an operator is already
watching for signs of trouble.

**Changed**

The installer helpers are inline in `install.sh` and `manager.sh`, and
`scripts/lib/` is gone. They were fetched over the network at startup so a
`curl | bash` one-liner could find them, and a fetch means the installer's own
behaviour comes from a git tag — so between a push and a release, `install.sh`
on main drew its output and asked its questions with the *previous* version of
that code. On a box with a flaky resolver or a proxy that blocks
raw.githubusercontent.com it could not start at all. Neither program downloads
anything now except the payload it installs, which is a checksummed release
archive.

`manager.sh` carries the same block byte for byte. The two are different
programs with different dispatchers, so each holds its own copy deliberately;
`test_lib_sourcing.py` asserts a helper is defined once per program, that the
two blocks are byte-identical, and that the eight sections are present by
banner name.

Removing the stderr noise surfaced a test that had been passing for six
releases without testing anything. `test_install_rejects_placeholder_password_fast`
asserted that a placeholder password is rejected — behaviour deleted at v1.0.0
when the owner password moved to the browser and `-p` became an accepted
no-op. Its assertion was `"placeholder" in r.stderr or "root" in r.stderr`,
and the stray path above lands in a directory named after the pytest tmpdir,
`/tmp/pytest-of-root/...`. So "root" matched the tmpdir name: the assertion
was satisfied by the very bug it sat next to. It now asserts what the
installer actually does — warns that `-p` is deprecated, says the password is
set in the browser, and never echoes the value back.

**Tests**

The byte counter behind the progress bar now has coverage. Fixing the stderr
leak left a gap: the `-f` guard that quietened the poll is also what gates the
measurement, and only the quiet half was tested — so a guard returning early,
or a fallback always printing 0, would have passed and left the bar frozen for
the whole download. A 5000-byte file must report 5000; an absent file must
report a bare integer 0, because the caller divides by it.

Nineteen test files each carried a helper byte-identical to the copy next
door; those moved to `conftest.py` — 153 lines out, 123 in, now in one place
instead of nineteen. Only bodies hashed identical in *every* file defining
them were moved: the same names recur elsewhere with different behaviour
(`_owner_headers` alone has nine variants across fourteen files), and merging
those would have changed what those tests assert while leaving them green.
Three small bot files and the two login files became one each.

909 pass.

## 1.0.4 — 2026-10-02

The release scan goes green.

**Fixed**

`build.yml` — Build and Test — has failed on every release since v1.0.0 on
30 September, including the three cut on 1 October. It runs Trivy with
`exit-code: 1` against CRITICAL and HIGH, and it found four:

- `libpcre2-8-0`, HIGH, fixed in 10.46-1~deb13u3
- `urllib3`, three HIGH and MEDIUM, fixed in 2.8.0

The first is the base image. `python:3.12-slim` ships whatever Debian had when
the tag was cut, so a release can carry a HIGH Debian has already fixed, and
nothing in the Dockerfile ever upgraded it. The runtime stage now does.

The second was in the lock at 2.7.0 and is now 2.8.0.

Both verified inside the built image rather than by reading the Dockerfile:
libpcre2-8-0 at 10.46-1~deb13u3, urllib3 at 2.8.0.

908 pass.

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
