# `ovm` — operator CLI reference

`ovm` is the panel manager for an installed OVManager: a single shell entry point
(`manager.sh` in the repo) that the installer copies to `/usr/local/bin/ovmanager`
with `ovm` as a symlink, and that every update refreshes — so the `ovm` on a host
always matches the code in that host's `/opt/ovmanager` tree, not your checkout.

Thirteen verbs. Anything longer is one flag away: `ovm help --all` carries every
option, the retired-name map, and which half of the tool runs where.

Three of them group their actions. Called bare, each lists what it can do rather
than starting a menu, so a script never blocks on a prompt:

| Command | Lists / does |
|---|---|
| `ovm tls` | the installed certificate, then `selfsigned` \| `le IP\|DOMAIN` \| `custom CERT KEY` |
| `ovm auth` | the owner credential, then `key` \| `reset` |
| `ovm url` | the live panel URL and where the prefix came from, then `set PREFIX` \| `reset` |

## The short list

```
ovm status              Service, health, version, panel URL  (--all for paths)
ovm logs [N|-f]         Last N lines, or follow live
ovm doctor [--fix]      Health checks; --fix applies the safe ones
ovm restart             Restart the panel
ovm enable | disable    Automatic start on or off

ovm tls                 Certificate — lists the options
ovm auth                Owner credential — lists the options
ovm url                 Panel URL — lists the options

ovm backup [--keep N]   Write a data backup now
ovm backup schedule     on | off | status — the host timer
ovm restore [NAME]      List backups, or restore one

ovm update              Staged update; recovers an interrupted one first
ovm rollback            Restore the pre-update code snapshot
ovm uninstall           Remove the app (--purge for data too)
```

Bare `ovm` prints that list and exits, with or without a terminal. It never opens
a menu: a provisioning script that invokes it must not wait for input.

## `.env` is yours

The installer writes `.env` once, at install. **Nothing in this tool ever edits it
again** — not `ovm auth reset`, not `ovm url set`, not `ovm tls`. Edit it freely;
changes take effect on `ovm restart`.

`ovm config` prints every effective setting and where it comes from, which is the
answer to "is the panel using this file or the database?":

| In `.env` — authoritative | Because |
|---|---|
| `DATA_DIR` | the database cannot be opened without it |
| `HOST`, `PORT` | the socket binds before anything is up |
| `JWT_SECRET_KEY` | read at startup; rotating it logs everyone out |
| `SSL_KEYFILE`, `SSL_CERTFILE` | where `ovm tls` puts the certificate |
| `PUBLIC_URL` | the address clients are given, behind a proxy |
| `ADMIN_USERNAME` | the owner login name |

Everything not named there is a database row: the url path, the owner credential,
the subscription prefix, proxy trust. `URLPATH` seeds from `.env` once at install
and has been a settings row ever since, so editing it afterwards changes nothing —
`ovm url` tells you which value is live.

`ovm auth rotate` (node) and `ovm tls` both *print* what to change rather than
changing it, for the same reason.

## Command surface

Every verb, with where it runs. "CLI" is the Python implementation in `cli/`, run
from the installed tree on a native install and from inside the container on a
Docker one. "host" is the shell in `manager.sh`, either because the command needs a
fact only the host has, or because it drives the system.

| Command | What it does | Root | Runs in |
| --- | --- | --- | --- |
| `ovm` | Prints the command list and exits 0. There is no menu | no | bash |
| `ovm help --all` | The full reference: every option, the retired names, where each half runs | no | bash |
| `ovm status` | Service state, panel health, version, panel URL | yes | CLI |
| `ovm status --all` (or `-a`) | Adds mode, port, data dir, install dir | yes | CLI |
| `ovm restart` | Restart the panel | yes | bash |
| `ovm enable` / `disable` | Toggle automatic start at boot | yes | bash |
| `ovm logs [N]` / `-f` | Last N journal/container lines, default 100, or follow | yes | host |
| `ovm doctor [--all]` | Health checks. Failures first with their fixes; `--all` lists every check | yes | CLI |
| `ovm doctor --fix` | Same checks, plus the safe automatic repairs | yes in practice | CLI checks, host fixes |
| `ovm tls` | Key, cert, expiry, then the options | yes | CLI + bash |
| `ovm tls selfsigned` | New self-signed certificate, then restart | yes | bash |
| `ovm tls le IP\|DOMAIN` | Let's Encrypt — one free-text field, ip or domain, detected | yes | bash |
| `ovm tls custom CERT KEY` | Install your own pair at the paths `.env` declares | yes | bash |
| `ovm auth` | Owner credential state, then the applicable options | yes | bash |
| `ovm auth key` | The one-time setup key, on an unclaimed panel | yes | bash |
| `ovm auth reset [-p PASS]` | Set a new owner password — the way out when the panel is unreachable | yes² | CLI |
| `ovm url` | The live panel URL, the prefix, and where the prefix came from | yes | CLI + bash |
| `ovm url set PREFIX` | Serve under a path of your choosing (`/` for the root) | yes | CLI |
| `ovm url reset` | Generate a fresh random path | yes | CLI |
| `ovm backup [--keep N]` | Write one verified data backup now | yes | CLI |
| `ovm backup schedule [on\|off\|status]` | Host-level auto-backup via a systemd timer | yes | bash |
| `ovm restore [NAME]` | List data backups, or restore one by name | yes | CLI |
| `ovm update [-v VERSION]` | Staged update: verified safety backup, code snapshot, verified release, maintenance mode, verification, automatic failover. **Recovers an interrupted update first** | yes | bash → `install.sh` |
| `ovm rollback` | Restore the newest pre-update code snapshot from `/var/backups` | yes | bash |
| `ovm config` | Every effective setting and its source. Read-only | yes | CLI |
| `ovm uninstall [--purge]` | Remove the app; data kept unless `--purge` | yes | bash → `install.sh` |

`docker logs` may need privileges you do not have as a normal user.
² `auth reset` validates the password *before* the root gate, so a bad password
fails the same way for root and non-root callers.

### Retired names

These still work, unchanged, and are mapped in `ovm help --all`. Nothing warns: a
deprecation line on every cron job that calls `ovm auto-backup` is noise, not
notice.

| Old | Now |
| --- | --- |
| `ovm https --self \|--domain D \|--ip \|--key F --cert F` | `ovm tls selfsigned` \| `le D` \| `le IP` \| `custom CERT KEY` |
| `ovm tls-status` | `ovm tls` |
| `ovm owner-claim` | `ovm auth key` |
| `ovm reset-password` | `ovm auth reset` |
| `ovm reset-urlpath` | `ovm url reset` |
| `ovm recovery` | `ovm url` |
| `ovm auto-backup [on\|off\|status]` | `ovm backup schedule [on\|off\|status]` |
| `ovm doctor-fix` | `ovm doctor --fix` |
| `ovm recover-update` | `ovm update` — it recovers an interrupted one first |
| `ovm start` / `stop` | `ovm restart` |

The CLI needs the install's virtualenv. If it is missing, the command says so and
tells you to run `ovm update` — it does not silently do something else. `ovm tls`
with no subcommand still prints its options on a box it cannot read, because that
is the one command whose job is to say what it can do.

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

They all read `.env`, which holds `JWT_SECRET_KEY` and the secret URL path — the
panel's only defence against scanners (the owner credential is a database row,
not a `.env` value). So "read-only"
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
sudo ovm doctor --all          # every check, not just the failing ones
sudo ovm doctor --fix           # same checks, applies the safe fixes
```

Output leads with what is wrong. A failing check is listed with its detail and, on
the next line in the same column, the command that fixes it:

```
  ✗ 2 problems

   Disk            4% free on /var
   fix             free space on /var
   Certificate     expires in 12d
   fix             ovm tls

    11 other checks passed — detail: ovm doctor --all
```

A clean run is one line — `✓ no problems — 13 checks passed` — because thirteen
passing checks used to spend fifteen lines saying the word "ok", which is a screen
nobody reads. `doctor` exits 1 when any check fails, so it works as a monitoring
gate.

| Check | Fails when | Auto-fix |
| --- | --- | --- |
| Service | not `running`/`active` | restart (`docker restart` or `systemctl restart`) |
| Auto start | systemd unit disabled | `systemctl enable` / `docker update --restart unless-stopped` |
| Certificate | the installed cert expires within 30 days, or is expired | none (`ovm tls`) |
| Update | an interrupted update left a journal or the write-block marker | none (`ovm update`, which recovers first) |
| Backup | no backup, or the newest is older than 7 days | none (`ovm backup`) |
| Permissions | the data dir is not `0700`, or the db/state files are not `0600` | tighten the modes |
| Disk | under 200 MB free on the data dir | none |

`--fix` re-checks each repair as it applies it, so what it prints describes the
state *after* the fix rather than before. Only the safe ones are applied: service
restart, autostart, file modes. Everything else is printed with its fix and left
to you.

## Backups

```bash
sudo ovm backup                       # one verified backup now
sudo ovm backup --keep 30             # keep 30 bundles
sudo ovm backup schedule status
sudo ovm backup schedule on --time 04:00 --keep 30
sudo ovm backup schedule off
sudo ovm restore                      # list what is available
sudo ovm restore ovmanager-pre-update-20260917-120000.ovmbak
```

`backup` calls the panel's own `create_panel_backup()`: the database is snapshotted
and bundled into `/var/lib/ovmanager/backups/ovmanager-backup-<stamp>-v1.ovmbak`, and
older bundles beyond `--keep` are pruned (default 14). `--keep` is 1–500. The
result prints the path, and the bundle's checksum is verified before it is called
one.

`backup schedule` is bash-only and manages the host: it writes
`ovmanager-backup.service` and `ovmanager-backup.timer` (daily `OnCalendar`,
`Persistent=true`) that run `ovmanager backup --keep N`, then enables the timer;
`off` deletes both units. `--time` is validated as `HH:MM`.

This is deliberately *not* the panel's own schedule. The web UI (*Settings →
Backup*) stores a schedule in the database and runs it in-process; the CLI command
drives a systemd timer. Pick one — running both means two backup schedules writing
the same directory.

`restore` with no name lists the backups with their dates and sizes and changes
nothing. With a name it takes a verified safety copy of the current state first, so
a restore cannot leave you with nothing to go back to.

## HTTPS

```bash
sudo ovm tls                                # key, cert, expiry — then the options
sudo ovm tls selfsigned                     # new self-signed certificate
sudo ovm tls le vpn.example.com             # Let's Encrypt, domain
sudo ovm tls le 2.28.122.51                 # Let's Encrypt, this host's IP
sudo ovm tls custom /etc/ssl/live/vpn.key /etc/ssl/live/vpn.crt
```

Called with no subcommand, `ovm tls` prints the installed certificate and then the
options above. It does that on a box it cannot read as well — the one command whose
job is to say what it can do must not be the one that cannot run.

`le` takes one free-text field and decides for itself whether it is an address or a
name, so you are not asked which kind of certificate you qualify for.

**Where the files go is declared by `.env`, not chosen by this command.**
`SSL_KEYFILE` and `SSL_CERTFILE` say where; `ovm tls` writes there. That used to be
two locations with a hidden winner — the panel preferred `DATA_DIR/tls/` over what
`.env` said, so an operator who installed a certificate at the declared path
watched the panel keep serving the old one with nothing in any log to explain it.
One declaration, one location. An install with no declaration gets
`/etc/ovmanager/tls`. An install that *does* declare keeps its paths forever.

An install that predates the rule, with a certificate in the old location, has it
copied onto the declared paths the first time `ovm tls` runs — a copy, never a
move, and never over a pair already sitting at the declared path. It says so when
it does, and says nothing when there is nothing to move.

## Account recovery

```bash
sudo ovm url                              # the live panel URL, and where the prefix came from
sudo ovm auth                             # credential state, then the applicable options
sudo ovm auth key                         # the one-time setup key, on an unclaimed panel
sudo ovm auth reset                       # prompts twice, hidden input
sudo ovm auth reset -p 'new-long-password'
OVM_PASS='new-long-password' sudo ovm auth reset
sudo ovm url set my-panel                 # serve under a path you choose
sudo ovm url reset                        # a fresh random path
```

`ovm auth reset` is the way out when the panel is unreachable — it writes the
owner's bcrypt hash in the panel database (`cli/password.py` is the only writer)
and never touches `.env`. It prompts for the password, or takes it from
`-p`/`OVM_PASS`; either way it restarts the panel before reporting. On Docker the
command runs the same CLI inside the container, where that database is.

Policy: single line, at least 8 characters, and not one of `change-me`, `changeme`,
`change_me`, `password123`, `admin123`. The value is never echoed or logged, and it
reaches the Python implementation through the environment rather than the command
line, so it never appears in `ps`.

`ovm url` reads the prefix from the *panel*, not from `.env` — `URLPATH` seeds the
database once at install and has been a settings row ever since, so a URL built
from the file is exactly the URL that 404s. `set` takes a path or `/` for the root;
`reset` mints a fresh random one rather than clearing to the root, because a random
prefix is the point of having one.

`ovm auth key` is for a panel nobody has claimed yet. Once claimed, the key file is
deleted and the command tells you to use `ovm auth reset` instead.

## Update, rollback, uninstall

```bash
sudo ovm update                # staged update to the latest release
sudo ovm update -v v1.1.0      # pin a release
sudo ovm update -y             # never prompt
CI=true sudo ovm update        # same as -y
sudo ovm rollback              # restore the newest pre-update code snapshot
sudo ovm uninstall             # remove the app, keep /var/lib/ovmanager
sudo ovm uninstall --purge -y  # also delete /var/lib/ovmanager (data + certs)
```

`update` is a six-step transaction run by `install.sh`: verified pre-update backup
(`/var/lib/ovmanager/backups/ovmanager-pre-update-*.ovmbak`) and code snapshot
(`/var/backups/panel-code-*.tar.gz`), staged verified release with `.env`
preserved, maintenance mode, activation, verification. A candidate that fails
health fails back to the previous version and restores the database if the migration
touched it.

**`update` finishes an interrupted update before starting a new one.** That is why
`recover-update` is a retired name rather than a separate command: it is the thing
you reach for when something looks wrong, so `update` is what should fix it. If the
recovery itself fails, `update` stops and says nothing was changed.

If the host reboots mid-transaction the panel stays in maintenance mode with writes
blocked until recovery runs. Recovery reads
`/var/lib/ovmanager/update-state.json`: an unknown phase is refused rather than
guessed, a corrupt journal is reported as one clean line, a half-staged candidate is
discarded, and an activated one is completed or rolled back. With nothing pending
it says so and exits 0.

`rollback` is the manual escape hatch: it extracts the newest
`/var/backups/panel-code-*.tar.gz` over the install dir, restarts, and waits up to
60s for health. It restores **code only** — not data — and dies with the snapshot
path if health is not restored.

`uninstall` shows what it will delete and asks before doing it. `--purge` needs the
word `purge` typed, not just the flag, so an unattended run cannot empty a data
directory.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Command succeeded. `ovm help` also exits 0 (usage goes to stderr). |
| 1 | `die` fired: not installed, missing config/`.env`, root required, password policy violation, another maintenance operation is running, backup failed, rollback/uninstall/update failure. Also: `status` when `/health` is unreachable, `doctor` when any check fails, and `backup`/`auth reset`/`url` when the operation failed. |
| 2 | Usage error from the CLI (unrecognised flag or command) or an aborted password prompt (EOF/Ctrl-C). `install.sh` also exits 2 when it is non-interactive and OVManager is already installed. |
| 130 | Interrupted (SIGINT/SIGTERM). |

`ovm status` and `ovm doctor` are real health gates: 0 means healthy, 1 means not.
`logs` and `ovm tls` (bare) return 0 even when they warn, so do not use them as
gates.

## Environment

| Variable | Effect |
| --- | --- |
| `OVM_APP_DIR` | Installed tree to operate on. Default `/opt/ovmanager`; also where `cli/`, `.venv/`, `install.sh` and `.env` are read from. |
| `OVM_DATA_DIR` | Data directory. Default `/var/lib/ovmanager`; holds `ovmanager-compose.yml` (whose presence marks a Docker install) and the operation lock. |
| `OVM_PASS` | Same as `ovm auth reset -p` (used when no `-p` is given). |
| `OVM_BIN_DIR` | Where `ovmanager`/`ovm` are installed (default `/usr/local/bin`); used when the backup timer units are written. |
| `OVM_STOP_TIMEOUT` | Seconds before a `systemctl stop`/`restart` is force-killed (default 20). |
| `CI=true`, `NONINTERACTIVE=1` | Imply `-y` (no prompts, confirmations auto-accepted). |
| `NO_COLOR` | Disable coloured output. Colour is already off when stdout is not a TTY. |
| `OVM_RUN_ID` | Identifier echoed in every error block; generated per run when unset. |

`update` and `uninstall` are executed by `install.sh`, which additionally reads
`OVM_MODE`, `OVM_PORT`, `OVM_PATH`, `OVM_ADMIN_USER`, `OVM_TLS`, `OVM_TLS_DOMAIN`
and `OVM_PUBLIC_URL`.
