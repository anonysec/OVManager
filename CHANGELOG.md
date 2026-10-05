# Changelog

## 1.0.48 — 2026-10-05

Installer: 1.0.47 still failed because `install -d … .uv-cache` ran
*after* `uv sync`. Now the cache directory is created right before the
sync step so the panel user can write to it from the start.

## 1.0.47 — 2026-10-05

Installer: fresh installs failed at `uv sync` because `/opt/ovmanager`
was mode 750 (no group write) and `uv` was invoked under sudo which made
`HOME=/root`, leaving the cache unwritable for the panel user. Now the
install dir is mode 2775 group-write, the version dir is chowned
root:ovmanager 2775, and `uv sync` runs as the panel user with
`UV_CACHE_DIR=$DATA_DIR/.uv-cache`.

## 1.0.46 — 2026-10-05

Cleanup: dropped dead code (scripts/bench, redundant dashboard/UI components,
single-use hooks and utils), centralised node-fanout concurrency into
backend/node/fanout.py (`run_bounded`, `gather_nodes`, `gather_background`)
removing every wrapper copy, and made the CSRF exempt set, sub-route bypass,
and Swagger `tokenUrl` resolve from `get_urlpath()` so the panel stays
prefix-agnostic under URLPATH.

installer: `host_of()` extracts the host from a URL; uninstall `--purge`
removes only panel-owned certs and skips shared `/etc/ssl/self-signed`.

`pytest`: 953 pass. `make lint` clean. `npm run verify` clean.

## 1.0.45 — 2026-10-05

Four live bugs the adversarial review of 1.0.44 found in 1.0.44's own fixes.
Two of them were introduced by 1.0.44 and are the reason this is a new version
rather than a re-tag.

**If you run more than one node, read the billing item first.** On 1.0.44 a
single user deletion mid-tick could zero every other user's traffic for that
tick, and every installed copy of 1.0.44 has that.

**Fixed**

A user deleted mid-tick cost every other user their traffic. The multi-node fix
that made 1.0.44 bill more than the first node refreshes a stale session object
before reading its counters; unguarded, that refresh raises when the row is
already gone, and the exception escaped the per-user loop and discarded the
whole node's batch. Measured: a bystander billed 3200 bytes before the fix and 0
after, deterministically. A deleted user has nothing to bill, so the refresh now
skips that row and carries on.

The last language clicked did not win. `loadLanguage` fetches the code-split
bundle before switching, so two rapid picks could both be in flight and the
slower one to resolve decided the outcome — the first click reached the screen.

The panel's own "request a certificate for this server's IP address" asked Let's
Encrypt for a private address on any host whose docker bridge or metadata NIC
sorts ahead of the public one. The installer had been fixed for exactly this and
the panel's toggle was missed. It now skips the private, loopback and link-local
ranges and IPv6.

`ovm restart` reported success over a service that had not restarted.
`service_action` ended every branch on a message that returns 0, so the warning
beneath it could never fire. The same shape as the `pkg_install` bug fixed in
1.0.44, in the sibling file.

The asset cache's path confinement did not cover the gzip sibling. It checked the
requested file but not the `.gz` file the compressed fast path actually opens, so
a symlink planted at that name inside `assets/` was served — with 200 and the
file's contents. Both are now confined by real path.

**Tests**

Three of 1.0.44's fixes had no working regression test, and could have been
reverted without noticing:

- The asset traversal test used a `..` payload that the pre-fix code already
  rejected, so the suite was green against the vulnerable version.
- The language test exercised `i18n.js`, which 1.0.44 did not change — it passed
  identically whether the pickers called the fixed helper or not.
- The Let's Encrypt IP fix had no test at all: reverting all four call sites still
  passed the full suite.

Each now fails against the code that precedes its fix.

## 1.0.44 — 2026-10-04

An unauthenticated file read, a way to hand your panel to a stranger, and
multi-node traffic that was never billed.

**Security**

`GET /assets//<path>` returned the contents of any file the panel could read,
with no authentication. The double slash survives into the request path, so the
relative part began with `/`, and `os.path.join(base, "/etc/passwd")` discards
the base entirely — the `..` test was decoration rather than a boundary. Paths
are now confined by real path, which also refuses a symlink out of the tree.

The owner could `DELETE` their own account. The owner row is what makes a panel
claimed, and the one-time claim key outlives the install that printed it —
only a successful claim unlinks it. Deleting yourself therefore handed the
panel to whoever ever saw that key. Changing the owner's status was already
refused; deleting was not.

Both login rate-limit buckets keyed on the source address, so a proxy pool was
handed a fresh 5-attempt and a fresh 20-attempt bucket on every request and the
owner's password could be tried without limit. Added a per-username bucket with
no address in its key.

`/health` returned the exact panel version to every internet client: the
gate read the direct peer, which behind nginx is always loopback, so "is this
local?" was true for everyone.

`ovm auth reset` changed the password and left every existing session valid.
An operator resetting a compromised account kept the intruder — the token is
still in the sessions table and the sliding idle timeout refreshes it on every
request, so it never expires. The panel's own reset already revoked; the two
paths disagreed for the same intent.

**Fixed**

A panel with two or more nodes billed the first node's traffic and discarded
every other node's, silently. `check_user_used_traffic` loads its user list once
and reuses it per node, and the write is a Core `UPDATE` the session never sees,
so the second node read counters from before the first wrote, rebuilt its
per-node map from that stale copy, and had its conditional write rejected
outright. A two-node panel billed 1000 bytes for 6000 real ones.

`ovm url reset` reverted on the next boot. The settings seeder ran on every
migration rather than only on a fresh install and treated a blank prefix as
unset, so it restored `.env`'s `URLPATH` over the operator's reset. An empty
prefix is a value — it means "serve at the root" — and this is the documented
way out of a forgotten prefix, so `ovm restart` put you straight back in.

`ovm status` printed the `.env` seed rather than the prefix being served, so
the URL it told you to open returned a blank 404 the moment the prefix changed.

`ovm url set /` was the one command that could not do what its own error
promised. Serving at the root is deliberate and the error names `/` as the way
to ask, but the slashes were stripped before the character check, so `/` became
the empty string and the length requirement rejected it. The panel's own reset
writes that same empty value, so it was reachable from the backend and from
nowhere in the CLI.

Switching the panel's language to Persian, Russian or Chinese loaded nothing:
all five pickers called `i18n.changeLanguage` directly instead of the
`loadLanguage` helper that fetches the code-split bundle first. The page flipped
to RTL with every string still in English.

Four keys used by confirmation dialogs (`resetUsage`, `deleteUser`,
`deleteAdmin`, `deleted`) existed in no locale, so those dialogs rendered the
raw camelCase identifier to the operator. Added to all four.

Logging in from a second browser tab left the first tab authenticated with no
role, so the owner-only pages were never registered and stayed missing until a
reload.

The installer's menu waited forever when stdin was a pipe and a terminal was
reachable — `echo 1 | bash install.sh` from a terminal, or any CI runner with a
pty. The numbered rewrite dropped the timeout the old keystroke reader had.
Answers on stdin are now read with a bounded window.

A failed package install ended the installer instead of falling back: the three
documented fallbacks behind that call were unreachable, and silently so, since
the caller discards its output.

The Let's Encrypt IP option took the first `hostname -I` field, which on a host
with a docker bridge or a cloud metadata NIC ahead of the public address is a
private IP that Let's Encrypt refuses.

The Ready card pointed at a page behind the authentication guard, so a first-run
operator holding a claim key was bounced to the login page with no way to claim.
`/claim` is gone: `/setup` now serves the claim form to an unauthenticated
visitor and the setup checklist to the owner.

The installer no longer asks for an owner username. It asked for one, took no
password, and wrote the answer to `.env` — where the claim endpoint was already
reading `ADMIN_USERNAME` from. It changed nothing.

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

## 1.0.48 — 2026-10-05

Cleanup: dropped dead code (scripts/bench, redundant dashboard/UI components,
single-use hooks and utils), centralised node-fanout concurrency into
backend/node/fanout.py (`run_bounded`, `gather_nodes`, `gather_background`)
removing every wrapper copy, and made the CSRF exempt set, sub-route bypass,
and Swagger `tokenUrl` resolve from `get_urlpath()` so the panel stays
prefix-agnostic under URLPATH.

installer: `host_of()` extracts the host from a URL; uninstall `--purge`
removes only panel-owned certs and skips shared `/etc/ssl/self-signed`.

`pytest`: 953 pass. `make lint` clean. `npm run verify` clean.
