# `ovm` — operator CLI reference

`ovm` is the panel manager for an installed OVManager: a single shell entry point
(`manager.sh` in the repo) that the installer copies to `/usr/local/bin/ovmanager`
with `ovm` as a symlink, and that every update refreshes — so the `ovm` on a host
always matches the code in that host's `/opt/ovmanager` tree, not your checkout.
Read and diagnostic commands are implemented once, in Python under `cli/`, and `ovm`
is the dispatcher that decides how to reach it. On a native install that is the
install's own virtualenv (`$OVM_APP_DIR/.venv/bin/python -m cli.main …`); on a Docker
install the same command runs *inside* the panel container, with the host supplying
the two facts a container cannot know (the service state, and the host's IP for the
panel URL).

Three commands cannot run in a container and are handled on the host instead:
`logs` (there is no `journalctl` in the container), `reset-password` and
`reset-urlpath` (the `.env` that has to be rewritten is on the host, not mounted into
the container at that path). `doctor --fix` is also host-side, because restarting a
service and changing a file mode are host operations. Certificate issuance
(`ovm https`), `recovery`, `rollback`, `auto-backup`, `update`, `recover-update` and
`uninstall` are shell by nature; `update`/`uninstall` simply `exec`
`$INSTALL_DIR/install.sh` so there is one copy of that logic. Without a terminal — or
with `-y`, `CI=true` or `NONINTERACTIVE=1` — the interactive paths do not block: menus
take their default answer and the password prompt fails loudly — with one
exception that matters: a destructive command (rollback, uninstall) **declines**
rather than proceeding, so an unattended run cannot replace a working install
with a snapshot. Pass `-y` to say yes deliberately.

## Command surface

| Command | What it does | Root | Runs in |
| --- | --- | --- | --- |
| `ovm` | Prints the command list on stderr and exits 0. There is no menu | no | bash |
| `ovm help`, `ovm -h`, `ovm --help` | The same list | no | bash |
| `ovm status` | Service state, panel health, version, panel URL | yes | CLI |
| `ovm status --all` (or `-a`) | Adds mode, port, data dir, install dir | yes | CLI |
| `ovm start` / `stop` / `restart` | Service control (Docker or systemd) | yes | bash |
| `ovm enable` / `disable` | Toggle automatic start at boot | yes | bash |
| `ovm logs [N]` | Last N journal/container lines, default 100 | yes | host |
| `ovm logs -f` | Follow the log | yes | host |
| `ovm doctor` | Twelve read-only checks (see below) | yes | CLI |
| `ovm doctor --fix`, `ovm doctor-fix` | Same checks plus auto-fix: restart service, enable autostart, tighten private file modes | yes in practice | CLI checks, host fixes |
| `ovm tls-status` | Read-only: key path, cert path, `notAfter` | yes | CLI |
| `ovm backup [--keep N]` | Create one verified data backup now | yes | CLI |
| `ovm auto-backup [status\|on\|off] [--time HH:MM] [--keep N]` | Host-level auto-backup via a systemd timer (see the note below) | yes | bash |
| `ovm https --self` (alias `ovm tls`) | New self-signed certificate, then restart | yes | bash |
| `ovm https --domain NAME` | Let's Encrypt certificate for a domain (needs port 80 free) | yes | bash |
| `ovm https --ip` | Let's Encrypt certificate for this host's public IP | yes | bash |
| `ovm https --key F --cert F` | Install your own key and certificate | yes | bash |
| `ovm recovery` | Panel URL and login name | yes | bash |
| `ovm reset-password [-p PASS]` | Rewrite the owner credential in `.env` and restart the panel | yes² | CLI when `-p` is given, host when it prompts |
| `ovm reset-urlpath` | Clear the panel URL prefix; the panel is served at `/` again | yes | host |
| `ovm update [-v VERSION]` | Staged update: verified safety backup, code snapshot, verified release, maintenance mode, verification, automatic failover | yes | bash → `install.sh` |
| `ovm recover-update` | Finish or roll back an update interrupted by reboot/power loss | only when recovery work is needed | bash → `install.sh` |
| `ovm rollback` | Restore the newest pre-update code snapshot from `/var/backups` | yes | bash |
| `ovm uninstall [--purge]` | Remove the app; data kept unless `--purge` | yes | bash → `install.sh` |

`docker logs` may need privileges you do not have as a normal user.
² `reset-password` validates the password *before* the root gate, so a bad
password fails the same way for root and non-root callers.

"CLI" means the Python implementation in `cli/`, run from the installed tree on a
native install and from inside the container on a Docker one. "host" means the shell
in `manager.sh` or `install.sh`, either because the command needs a host-only fact or
because it drives the system. `auto-backup` is host-side because it manages a systemd
timer rather than the panel's own schedule.

The CLI needs the install's virtualenv. If it is missing, the command says so and
tells you to run `ovm update` — it does not silently do something else.

## Status and service

```bash
sudo ovm status                 # Service, Health, Version, Open
sudo ovm status --all           # + Mode, Port, Data, Install

sudo ovm restart
sudo ovm stop && ovm start
sudo ovm enable                 # autostart on boot (systemd enable / docker restart policy)
sudo ovm disable                # autostart off; the running panel is not stopped
```

`status` reads the installed `.env` for `PORT`, `URLPATH` and `SSL_KEYFILE`, then
probes `http(s)://127.0.0.1:<port>/health`. Service state comes from
`systemctl is-active ovmanager.service` (native) or `docker ps` (Docker, detected by
the presence of `/var/lib/ovmanager/ovmanager-compose.yml`). Auto-detected mode is
`native` or `docker`.

`status` prints the rows to stdout and exits `0` when the panel answers, `1` when it
does not.

## Logs

```bash
sudo ovm logs                   # last 100 lines
sudo ovm logs 500               # last 500 lines
sudo ovm logs -f                # follow
```

Docker installs read `docker logs ovmanager`; native installs read
`journalctl -u ovmanager.service`. Only a line count or `-f` is accepted as the
argument — anything else is rejected as an unknown option. The exit status is
whatever `docker logs` / `journalctl` returned.

This one is handled on the host rather than in the container, which has neither
`docker` nor `journalctl`.

## Root

**Every `ovm` command requires root**, including the read-only ones. This is
deliberate and enforced, not a side effect of file permissions.

They all read `.env`, which holds `ADMIN_PASSWORD_HASH`, `JWT_SECRET_KEY` and
the secret URL path — the panel's only defence against scanners. So "read-only"
meant "changes nothing", not "discloses nothing". `ovm status` prints the panel
URL including that path; `ovm recovery` prints it directly.

```bash
sudo ovm status
sudo ovm doctor
```

Two notes on what this is not:

- **The web panel needs no root.** Any account can log in over HTTPS. Root is
  only about operating the box, not using the panel.
- **Installing has always required root**, because the installer writes
  `/opt/ovmanager`, `/var/lib/ovmanager`, `/etc/systemd/system`,
  `/usr/local/bin` and firewall rules. `install.sh --help` and the dry plan
  work for anyone.

Until 1.0.21 the read-only commands appeared to work without root in the
documentation, and in practice failed with `scripts/lib not found`, because the
install tree shipped owned by uid 1001 — the release runner's uid, which does
not exist on the target. Both are fixed: the tree is root-owned, and the
requirement is now stated at the CLI rather than implied by a directory mode.

**The panel itself is not root.** Since 1.0.25 it runs as a dedicated
`ovmanager` service account, the same shape the Docker image uses for its
`appuser`: it is a network-facing service that parses untrusted input, so a
compromise of the web app should not be a compromise of the host. It reads its
own code and `.env` through that account's group, owns its data directory, and
reads the TLS key the same way. `ovm doctor` reports which account it is using.

One consequence: the panel can no longer update itself, because replacing the
tree and restarting the unit needs root. The in-app update button says so and
names the command — `sudo ovm update` — rather than trying and failing.

## Health checks

```bash
sudo ovm doctor                 # read-only
sudo ovm doctor --fix           # same checks, applies safe fixes
sudo ovm doctor-fix             # identical to --fix
```

Checks and the fixes `doctor-fix` will attempt:

| Check | Fails when | Auto-fix |
| --- | --- | --- |
| Service | not `running`/`active` | restart (`docker restart` or `systemctl restart`) |
| Auto start | systemd unit disabled | `systemctl enable` / `docker update --restart unless-stopped` |
| Certificate | the installed cert expires within 30 days, or is expired | none (`ovm https`) |
| Update | an interrupted update left a journal or the write-block marker | none (`ovm recover-update`) |
| Backup | no backup, or the newest is older than 7 days | none (`ovm backup`) |
| Permissions | the data dir is not `0700`, or the db/state files are not `0600` | tighten the modes |
| Disk | under 200 MB free on the data dir | none |
| Config perms | native: `.env` is not `0600`. Docker: `.env` is not readable by the container's group | `chmod 600` (native) |
| Data dir | `/var/lib/ovmanager` missing | none (reinstall) |
| Panel health | `/health` not reachable | none (`ovm logs`) |
| Worker | the scheduled-jobs process is not running, so backups and limit enforcement have silently stopped | none (`ovm restart`) |
| Service account | the panel itself is running as root | `ovm update` (provisions a service account) |

Each failing row prints the command that fixes it. `doctor` exits 1 if any check
fails, so it is usable as a health gate in a script — see
[Exit codes](#exit-codes).

The Worker check reports on the lock the jobs process holds for its lifetime,
so a panel whose worker has died reads as unhealthy even though the web
server is fine. That is deliberate: the panel looking healthy while the daily
backup and traffic-limit enforcement are both off is the failure worth
catching.

On a Docker install the "Permissions" check is reported as `container-managed` (the
data directory belongs to uid 1000 inside the container) and "Config perms" checks
that the group can read the `.env`, which is what the container needs.

## Backups

```bash
sudo ovm backup                    # one verified backup now
sudo ovm backup --keep 30          # keep 30 tarballs/bundles
sudo ovm auto-backup status
sudo ovm auto-backup on --time 04:00 --keep 30
sudo ovm auto-backup off
```

`backup` calls the panel's own `create_panel_backup()`: the database is snapshotted
and bundled into `/var/lib/ovmanager/backups/ovmanager-backup-<stamp>-v1.ovmbak`, and
older bundles beyond `--keep` are pruned (default 14). The result is printed as
`Verified backup <path>`. `--keep` (1–500, default 14) is honoured.

`auto-backup` is bash-only and manages the host: it writes
`ovmanager-backup.service` and `ovmanager-backup.timer` (daily `OnCalendar`,
`Persistent=true`) that run `ovmanager backup --keep N`, then enables the timer;
`off` deletes both units. `--time` is validated as `HH:MM` and `--keep` as 1–500.

This is deliberately *not* the panel's own schedule. The web UI (*Settings →
Backup*) stores a schedule in the database and runs it in-process; the CLI
command drives a systemd timer. Pick one — running both means two backup
schedules writing the same directory.

Data restore is **not** a CLI command: restore an `.ovmbak` bundle from
*Settings → Backup* in the panel (or the `maintenance/backup/restore` API, owner
only).

## HTTPS

```bash
sudo ovm tls-status              # read-only: key, cert, expiry — no root, no prompts
sudo ovm https --self        # new self-signed certificate
sudo ovm https --domain vpn.example.com
sudo ovm https --ip          # Let's Encrypt for this host's public IP
sudo ovm https --key /etc/ssl/live/vpn.key --cert /etc/ssl/live/vpn.crt
sudo ovm tls --self          # alias of ovm https
sudo ovm tls-status          # read the current certificate first
```

`tls-status` reads `SSL_KEYFILE` / `SSL_CERTFILE` from the installed `.env` and
prints the certificate's `notAfter`. It never writes anything and always exits 0.

`https` (and its `tls` alias) is the only command that mutates certificates, and it
is always interactive — it always needs a terminal, and it re-reads the current
state before offering:

```
1) Self-signed (regenerate)     -> openssl self-signed pair in /etc/ssl/self-signed (10 years)
2) Let's Encrypt for a domain  -> acme.sh standalone, needs port 80 free
3) Let's Encrypt for this IP   -> acme.sh short-lived IP certificate, needs port 80 free
4) Custom key + cert paths     -> copied into /etc/letsencrypt/panel
0) Back
```

After a successful issuance the new key/cert paths are written to `.env`, private
files are `chown 1000:1000` + `chmod 600` (cert `644`), and the service or
container is restarted. Choosing an option takes the maintenance operation lock, so
it refuses to run while another `ovm` maintenance command is in flight.

## Account recovery

```bash
sudo ovm recovery                      # panel URL and login name (read-only)
sudo ovm reset-password                # prompts twice, hidden input
sudo ovm reset-password -p 'new-long-password'
OVM_PASS='new-long-password' sudo ovm reset-password
sudo ovm reset-urlpath
```

`recovery` prints the panel URL and login name and changes nothing. The two
things the old menu could do from there are commands of their own:
`reset-password` and `reset-urlpath`.

`reset-password` rewrites only the owner credential line in the installed `.env`
(preferring `ADMIN_PASSWORD_HASH=` with a bcrypt hash; plaintext only if the panel's
hasher is unavailable) and preserves the file's existing mode and group — which
matters on Docker, where the container reads the file through a group. Either form
restarts the panel so the new credential takes effect; on Docker the container is
**recreated** rather than restarted, because a restart reuses the environment the
container was created with and would leave the old password live. The prompting form
additionally waits 12s for `/health` and prints the login name and URL.

Policy: single line, at least 8 characters, and not one of `change-me`, `changeme`,
`change_me`, `password123`, `admin123`. The value is never echoed or logged, and it
reaches the Python implementation through the environment rather than the command
line, so it never appears in `ps`. With no `-p`/`OVM_PASS` the prompt needs a
terminal — and in that case the rewrite is done by the host script, since a prompt
has no argument to pass.

`reset-urlpath` runs the panel's own `main.py --reset-urlpath` entrypoint (via
`docker exec` on Docker installs) and clears the secret prefix; requests to `/`
serve the panel again. Set a new path afterwards in *Settings → General*.

## Update, rollback, uninstall

```bash
sudo ovm update                # staged update to the latest release
sudo ovm update -v v1.1.0      # pin a release
sudo ovm update -y             # never prompt
CI=true sudo ovm update        # same as -y
sudo ovm recover-update        # after an update was interrupted
sudo ovm rollback              # restore the newest pre-update code snapshot
sudo ovm uninstall             # remove the app, keep /var/lib/ovmanager
sudo ovm uninstall --purge -y  # also delete /var/lib/ovmanager (data + managed cert)
```

`update` is a six-step transaction run by `install.sh`: verified pre-update backup
(`/var/lib/ovmanager/backups/ovmanager-pre-update-*.ovmbak`) and code snapshot
(`/var/backups/panel-code-*.tar.gz`), staged verified release with `.env`
preserved, maintenance mode, activation, verification. A candidate that fails
health fails back to the previous version and restores the database if the migration
touched it. If the host reboots mid-transaction the panel stays in maintenance
mode until `ovm recover-update` runs: that command reads
`/var/lib/ovmanager/update-state.json`, discards a half-staged candidate, or
completes/restores an activated one, and is a no-op ("No interrupted update needs
recovery") when nothing is pending.

`rollback` is the manual escape hatch: it extracts the newest
`/var/backups/panel-code-*.tar.gz` over the install dir, restarts, and waits up to
60s for health. It restores **code only** — not data — and dies with the snapshot
path if health is not restored.

`uninstall` and `update` are implemented in `install.sh` and re-implement nothing:
`ovm` passes through `-y`, `-j`, `--purge` and `-v VERSION`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Command succeeded. `ovm help` also exits 0 (usage goes to stderr). |
| 1 | `die` fired: not installed, missing config/`.env`, root required, password policy violation, another maintenance operation is running, backup failed, rollback/uninstall/update failure. Also: `status` when `/health` is unreachable, `doctor`/`doctor-fix` when any check fails, and `backup`/`reset-password`/`reset-urlpath` when the operation failed. |
| 2 | Usage error from the CLI (unrecognised flag or command) or an aborted `reset-password` prompt (EOF/Ctrl-C). `install.sh` also exits 2 when it is non-interactive and OVManager is already installed. |
| 130 | Interrupted (SIGINT/SIGTERM). |

`ovm status` and `ovm doctor` are real health gates: 0 means healthy, 1 means not.
`tls-status` and `logs` return 0 even when they warn, so do not use them as gates.

## Environment

| Variable | Effect |
| --- | --- |
| `OVM_APP_DIR` | Installed tree to operate on. Default `/opt/ovmanager`; also where `cli/`, `.venv/`, `install.sh` and `.env` are read from. |
| `OVM_DATA_DIR` | Data directory. Default `/var/lib/ovmanager`; holds `ovmanager-compose.yml` (whose presence marks a Docker install) and the operation lock. |
| `OVM_PASS` | Same as `ovm reset-password -p` (used when no `-p` is given). |
| `OVM_BIN_DIR` | Where `ovmanager`/`ovm` are installed (default `/usr/local/bin`); used when the auto-backup timer units are written. |
| `OVM_STOP_TIMEOUT` | Seconds before a `systemctl stop`/`restart` is force-killed (default 20). |
| `CI=true`, `NONINTERACTIVE=1` | Imply `-y` (no prompts, confirmations auto-accepted). |
| `NO_COLOR` | Disable coloured output. Colour is already off when stdout is not a TTY. |
| `OVM_RUN_ID` | Identifier echoed in every error block; generated per run when unset. |

`update` and `uninstall` are executed by `install.sh`, which additionally reads
`OVM_MODE`, `OVM_PORT`, `OVM_PATH`, `OVM_ADMIN_USER`, `OVM_TLS`, `OVM_TLS_DOMAIN`
and `OVM_PUBLIC_URL`.

## Troubleshooting

**Panel shows "unreachable" in `status`/`doctor` but the panel is up.** The health
probe pins the certificate named by `SSL_CERTFILE` in `.env` and deliberately does not
check the hostname, because the installer's certificate carries the public IP as its
CN and has no SANs while the probe dials `127.0.0.1` — a name check fails on a
perfectly healthy self-signed panel. If the certificate file cannot be read the probe
falls back to unverified verification, like `curl -k`. A failure here therefore means
the served certificate really does not match the installed one: compare `ovm
tls-status` with `ovm logs`, then issue a trusted certificate with `sudo ovm https`
(option 2 or 3).

**Docker: the owner password does not work, or the panel will not start.** Before
1.0.12 the panel's `.env` was passed to the container through compose `env_file`, and
compose expands `$NAME` inside such values — which truncates a bcrypt password hash at
its salt (measured: 83% of hashes start with a letter or dot, i.e. a valid variable
name). The symptom is either `ADMIN_PASSWORD_HASH must be a bcrypt hash` on boot, or a
correct password being rejected. 1.0.12 mounts the file read-only at `/app/.env`
instead. Upgrading repairs it: the compose file is regenerated, the `.env` becomes
`0640 root:<gid>`, and the hash reaches the container intact. Confirm with
`sudo ovm doctor` — "Config perms" should say `shared with the container`.

**Docker: `Config perms` says the container cannot read the config.** The `.env` must
be `0640` and owned by the group the image creates for it (`ovpanel`). `sudo ovm
doctor` prints the exact `chgrp`/`chmod` to run. It must never be `0600` (the panel
cannot read its own configuration) or owned by uid 1000 (that would expose the admin
hash and the JWT secret to the first human user on the host).

**`ovm` says the panel virtualenv is missing.** The Python implementation runs from
`$OVM_APP_DIR/.venv`; a half-finished or interrupted install can leave it absent. Run
`sudo ovm update` to restore the tree, or `sudo ovm rollback` if an update left it that
way.

**A command exits 2 with `unrecognized arguments`.** The flag was not one the command
accepts. `-a`, `--install-dir` and `--data-dir` work on either side of the subcommand
(`ovm --all status` and `ovm status --all` are the same). To call the implementation
directly: `cd $OVM_APP_DIR && .venv/bin/python -m cli.main status --all`.

**Certificate expiring or browser warning.** `ovm tls-status` shows the `notAfter`
date. Renew or replace with `sudo ovm https` (option 1 regenerates the self-signed
pair, options 2/3 need port 80 free for the ACME standalone challenge, option 4
takes your own key/cert). A self-signed certificate is expected to warn in
browsers; the connection is still encrypted.

**Wrong URL / 404 on the panel path.** The live prefix lives in the database and is
only mirrored from `.env` at install time, so `ovm status` can show a stale path.
`sudo ovm reset-urlpath` clears it; the panel is then served at `/`. Set a new
prefix in *Settings → General*.

**Lost owner password.** `sudo ovm reset-password` (or `-p`), or entry 2 of
`sudo ovm recovery`. It rewrites only the credential line in `.env` and restarts
the panel.

**Interrupted update (panel in maintenance mode).** `sudo ovm recover-update`. It is
a no-op when nothing is pending and needs root only when it actually has work to do.
`sudo ovm rollback` restores the previous code tree if you must get back before the
release is healthy; a database safety backup is listed in
`/var/lib/ovmanager/backups`.

**"Another maintenance operation is running".** A lock directory
`/var/lib/ovmanager/.operation.lock` serialises `backup`, `https` and
`doctor --fix`. A lock whose recorded PID is dead is removed automatically; if the
PID is alive, wait for it (or investigate that process) before retrying.

**Low disk.** `ovm doctor` fails the disk check under 200 MB free on the data dir.
`sudo ovm backup --keep 7` prunes old bundles. `doctor --fix` also flags private files
that are not `0600`/`0700` and tightens their modes.

**Nothing prompts.** `ovm` without a command needs a TTY, otherwise it exits 1 with
"No terminal". Prompting is suppressed by `-y`, `CI=true` and
`NONINTERACTIVE=1`; commands that require input (the `https` and `recovery` menus,
interactive `reset-password`) then fall back to their safe default or fail loudly.
