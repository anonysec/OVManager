# Installer and CLI design — decided

> Status: **shipped in OVManager 1.0.0, except where noted below.** Decisions 1 to
> 4 and the CLI work (bare invocation prints the list, `restore`, `completion`,
> `version-script`) are in the code. Still open: the command-name convergence with
> OVNode (`ovm recovery` versus `ovn credentials`), and OVNode's read-only commands
> reporting a default instead of an error when `.env` is unreadable. Supersedes the
> earlier proposal of the same name (which hedged between two structures) and the
> five ADR proposals deleted on 2026-09-29. Line numbers are from a working-tree
> read on 2026-09-29 and will drift.

## Constraints

1. **Two separate installers.** OVManager and OVNode stay separate repositories with
   separate `install.sh` and separate management commands. This converges their
   design, never their artifacts.
2. **Fewer flags.** Today: 31 flags and 25 environment variables across the two.
3. **Credentials live in the database, not `.env`.** `.env` is configuration; a
   password is data. The panel already obeys this — `set_owner_password` writes the
   owner row and never `.env`.

## The five decisions

### 1. Fetch the libs at startup and source them

One source of truth for the shared helpers, and `install.sh` stops carrying a copy.

Today `install.sh` cannot source `scripts/lib/*.sh` because it must be standalone, so the
46 lib functions are copy-pasted into it — **458 lines, 23% of the file**, held in sync by
a 45-name allowlist. The libs total ~23 KB across 7 files.

**Fetch them as the first action, then everything else uses the real helpers:**

```
1. prologue        set -e, identity globals (REPO, VERSION, APP_SLUG, PANEL_USER …)
2. fetch scripts/lib/*.sh for VERSION into a staging dir, then source them
3. parse flags, detect OS/arch, check root
4. wizard / unattended defaults
5. review card
6. install
```

Pinned to the **installer's own** `VERSION`, read from the immutable tag URL, **staged and
only sourced if every file arrives** — a partial set must never be sourced. If they cannot be fetched, die naming the URL: the installer genuinely cannot run
without them, so that must be one clear error, not a mysterious failure twenty lines later.

**Not the `--version` target.** The libs are installer infrastructure, not application code,
so `install.sh -v v1.0.2` must fetch *this* installer's libs and only pin the app tarball.
Pinning the libs to the target would break the feature outright: any version predating the
split has no libs at its tag, so installing an older release would fail on the first fetch.
The converse is safe — an installer released before the split is self-contained and never
fetches libs at all, so there is no version that needs libs it cannot have.

**Why not the other three:**

| | |
|---|---|
| Manager sources `install.sh` | **Blocked, and not obviously so.** `manager.sh` needs `install.sh` as *both* a library (source it for the 46 functions) and an executable (`exec install.sh update`). The tests stub the executable to assert delegation, so sourcing that stub breaks every function, while sourcing a real one makes the delegation tests install for real. |
| Generate `install.sh` from the libs | Needs a generator **plus a mandatory regenerate-and-diff CI check**, because `release.yml` packs `git archive HEAD` — a stale artifact ships to every installed box through `ovm update`. Every release diff becomes a full-file rewrite. |
| Fetch the tarball before the wizard, source from it | Works and needs no second fetch, but reorders a 2,000-line installer's control flow and needs a full E2E. The libs are 23 KB against a ~9 MB tarball, so fetching them up front is the cheaper way to get the same result. |
| **Fetch the libs at startup** | **No reorder, no generator, no build step, no duplicate** |

**Deletes:** 458 duplicated lines in OVManager, ~295 in OVNode, `tests/test_lib_parity.py`
in both, and the five functions that are dead in `install.sh` *only* because the parity
test demands a twin for every lib function (`rand_hex`, `has_tty`, `env_get`, `env_set`,
`latest_snapshot`).

**Cost, and it is not zero:** a second network resource at startup. The tarball fetch
already exists and this adds a small one before it; staging means a failure is one clear
error rather than a half-defined environment.

**As implemented in OVManager (2026-09-29), one deviation:** `_libs_install` sources
`$SCRIPT_DIR/scripts/lib` when the whole set is already beside the script — an installed
tree, or a checkout — and fetches only when it is not. A curl-piped installer is a lone
file in `/dev/fd` or `/tmp`, so the standalone case is the fetch the rest of this section
describes; the local path keeps the test suite offline and hermetic, which a fetch-per-run
would otherwise make impossible. The fetch is all-or-nothing into a `mktemp -d` staging
dir, and every failure names the URL it could not read. The base URL is
`OVM_LIB_BASE`-overridable — for forks and offline mirrors, and it is how the tests drive
the fetch without the network.

**The real work is in the tests, not the installer.** `tests/test_installer_sh.py` reads
`install.sh` as text to extract function bodies — **30 `_extract_function` call sites** —
and asserts on file contents in ~6 more places. Once the bodies move to the libs, the
helper must search `install.sh` *then* `scripts/lib/*.sh`, and those readers must read the
concatenation. Budget for that; it is mechanical but it is most of the diff.

### 2. One code path per setting

One helper serves both modes:

```bash
prompt_or_default() {   # VARNAME "prompt text" "default" [ENV_NAME]
    if [[ "$NONINTERACTIVE" == "1" ]]; then
        printf -v "$__var" '%s' "${!__env:-$__default}"
    else
        read -rp "$__prompt" "$__var"
    fi
}
```

Every prompt *is* its own env override. Non-interactive is `NONINTERACTIVE=1` **or** no
TTY, in one commented place.

**This is the whole reason to do it:** interactive and unattended stop being two code
paths, so they cannot disagree. They already do — OVNode's `install.sh -i -y` yields
**TCP** where `install.sh -y` yields **UDP**.

### 3. Three flags

```
install.sh                  the recommended install; no questions if not a TTY
  -y, --yes                 force unattended on a TTY
      --docker              container runtime
  -h, --help
```

Everything else is a prompt with an env override (decision 2). Settings that shape what
gets written — node name, API key, VPN ports, protocol, IPv6, NAT — stay install-time,
as `OVM_*` / `OVN_*` env vars rather than flags. Settings that do not — URL path, admin
user, TLS mode — move to `ovm` / `ovn` after install.

Comparable tools ship one flag or none. We ship 31.
No popular panel uses a `--config FILE`, so don't add one.

Per-flag triage of today's surface: `--mode` is deleted rather than validated (`--mode
docer` currently installs native, silently); `--docker` is the boolean it always was;
`--tls*` collapse into `OVM_TLS_MODE` + `OVM_TLS_DOMAIN`; `-p/--pass` is deleted with
decision 4.

### 4. Do not mint the owner password at install time

The claim-key model, which is the only one that removes the failure class rather than
mitigating it:

```
install.sh  →  prints a one-time claim key, no secret
ovm owner-claim  →  reprints a fresh key
browser  →  paste the key, choose the owner password
```

The account does not exist until it is claimed, so there is nothing to lose in
scrollback, nothing for `--quiet` to swallow, and no plaintext password in any file —
which is constraint 3 satisfied by construction rather than by care. A claim key can be
regenerated freely *because* it is not the credential.

**Cost, stated plainly:** one extra browser step for a beginner. Worth it, because the
alternative is the current position — we print a password *and* the only recovery is
`ovm reset-password`.

The **node API key** is different in kind: it is shared configuration the agent reads
from `.env` on every boot, so it cannot move to a claim flow. Keep generating it, keep
printing it once, and keep `ovn credentials` (added in `f487983`) as the recovery path.

### 5. Print less, and never degrade silently

Our card is longer than the minimal ones, but those are short because they have
nothing to say — no credentials, and a dashboard that refuses IP access at all.
Their brevity is a consequence, not a virtue.

Keep: URL, login, next action, and the self-signed browser warning — that one is not
noise, it is the difference between "expected" and "is this broken?".

Drop: the docs URL (it is in `ovm help`), the standalone reset-password line (fold into
the manage line), and the duplicated "or type address, port, API key" alternative.

**Name the degradation** instead of proceeding quietly:

```
⚠ SSL Certificate: Skipped — panel is HTTP-only. Use a reverse proxy or SSH tunnel.
```

## Target structure

```
install.sh          ~180 lines — the only file curl'd
scripts/lib/        the real implementation, split by concern (already exists:
                    51/132/25/86/47/185/56 lines, each doing one job)
manager.sh          thin dispatcher; sources the same libs; no duplicated functions
```

`install.sh` keeps, and keeps last, its `BASH_SOURCE == $0` guard (`install.sh:1986`),
so tests can source functions out of it as several already do.

`manager.sh` needs **no structural change at all** — it already sources the libs from
`$INSTALL_DIR/scripts/lib`. It only has to stop being a second copy of anything.

## What to take from the field, and what to refuse

**Take:** lib bootstrap-and-source with an atomic swap, so a partial refresh never
leaves a half-updated set; one prompt helper that is also its own env override; a
root-only credentials file; the claim key; `@`-style subcommand dispatch; and naming
a degradation out loud instead of proceeding quietly.

**Refuse:** a blanket refusal of IP access — defensible for operators, hostile to a
beginner with no domain, which is our audience. Ending the install inside a `tail -f`
of the app's own logs, so the installer never returns. A `read -p "override? (y/n)"`
with no safe default. And insecure defaults: the most popular installer out there is
the counterexample, not the template.

**Also offer, without making it the only path:** a documented download-then-inspect
two-step next to the one-liner, as some projects' docs do. The one-liner form that works
is `bash <(curl -fsSL …)` — process substitution keeps the terminal as stdin, so the
wizard still runs; `sudo` in front of it breaks it (`sudo` closes fd 3+).

## The CLI (`ovm` / `ovn`)

The installer hands off to the CLI, so it is the same design question. Both CLIs are
close to right; the problems are that they disagree with *each other*, and that some of
what they claim about themselves is false.

### One command name per job, in both repos

| job | OVManager today | OVNode today |
|---|---|---|
| show registration values | `recovery` | `credentials` |
| certificate status | `tls-status` | `tls` (a **menu**) |
| issue a certificate | `https --self\|--domain\|--ip\|--key F --cert F` | `tls` (same menu) |

Same job, different words. Converge on `credentials`, and on `tls` (status) / `https`
(issue, flag-driven) in both. Cosmetic churn — it should ride along with the flag cut,
not get its own release.

### Bare invocation prints the command list — never a menu

OVManager already does this, and its own comment says why: *"a stray invocation in a
script cannot start waiting for input."* OVNode does the opposite — `ovn` opens a
numbered menu, and `ovn tls` is a menu *command*. Both block a script that runs them by
accident. The comparable tools print usage. **Delete `manager_menu` and the
`ovn tls` menu; use flags.**

### A read-only command that cannot read must say so, not guess

The worst defect in either CLI, and it is verified:

```
$ sudo -u nobody ovn status          # .env is 0600 root, as in production
  Agent              inactive
  Health             unreachable
  Version            unknown
  OpenVPN            inactive
$ echo $?
0
```

Every lookup reads `.env`, `env_get` returns empty on an unreadable file, and the code
falls back to defaults — so a **perfectly healthy node reports itself broken, and exits
0**. `ovn credentials` gets this right (*"Must run as root."*); `status` does not.

**Rule: distinguish "not installed" from "cannot read".** If `.env` exists but is not
readable, die with `Cannot read $APP_DIR/.env — run with sudo.` Never fall back to a
default that looks like data. Applies to every read-only command in both repos, and
needs a test — the unprivileged run is cheap (see `test_manager_sh.py`).

### Help is generated from the parser, and the env claim must be true

Two failures of self-description, one per repo:

- **OVNode's help says** *"every flag has an OVN_\* env equivalent"*. Enumerating the
  names it actually reads gives 21 (`OVN_APP_DIR OVN_BIN_DIR OVN_BRANCH OVN_DOCKER
  OVN_IPV OVN_KEY OVN_NAME OVN_NO_NAT OVN_PORT OVN_PROTO OVN_PURGE OVN_QUIET OVN_REPO
  OVN_SRC OVN_STOP_TIMEOUT OVN_TLS OVN_TLS_CERT OVN_TLS_DOMAIN OVN_TLS_KEY
  OVN_VPN_PORTS OVN_YES`). **Neither `--keep` nor `-v/--version` has one.** The claim is
  false for two of its own flags.
- **OVManager's help omits 7 of its flags** (`-p --mode --tls --tls-domain --tls-key
  --tls-cert -i`) and 3 of its remaining env names (`OVM_BIN_DIR`, `OVM_PANEL_USER`,
  `OVM_STOP_TIMEOUT`; `OVM_ADMIN_PASS` is read nowhere and should go). It also leaks
  implementation into user-facing text — *"Status, doctor, tls-status and backups run
  from the Python CLI in cli/"*. The operator does not care which language a subcommand
  is written in.

One table drives the parser and the help, so neither can drift — the same idea as the
installer flags.

### Two commands missing from both

- **`restore`.** Both repos take backups; neither ships a way to restore one. `rollback`
  restores *code* from a snapshot, and the only mention of data restore is an error
  message pointing at `/var/backups`. A backup you can only
  restore by hand is half a feature.
- **`completion`.** Bash completion. Cheap, and with ~20 subcommands
  it is the difference between remembering them and reading `--help`.

Worth adding for support, given the CDN caches for ~5 minutes and stale installers are
therefore normal: print the **script's own commit** (`install.sh version-script`, as
does with a baked commit SHA). "Which installer did you actually run?" is a
question the release process already knows it will be asked.

### Refused from the field

`edit` / `edit-env` (drop the operator into `nano` on a live `.env`, unvalidated, no
backup); `tui` (OVManager deliberately removed its interactive menus, per its own
`main()` comment — do not reintroduce what was removed); and a `cli` passthrough that
puts a *second* command language under the first — a nested namespace is a worse
interface than one flat set.

## Migration order

1. **Make read-only commands report an unreadable `.env` instead of guessing** — a bug,
   not a refactor, and it stands alone. `ovn status` currently reports a healthy node as
   broken, and exits 0.
2. **Fetch the libs at startup, then delete the duplicated bodies from `install.sh`** in
   both repos, and update the test helper that reads `install.sh` as text (30 call sites).
   Verify with a full E2E: a fresh install, an update, and `uninstall --purge`.
   *(Done in OVManager — 46 bodies gone, the helper searches `install.sh` then the libs.
   No runtime E2E has been run on it yet.)*
3. **Delete `test_lib_parity.py`** and add a test asserting no shell function is defined
   in two files. This is now verifiable directly rather than by comparing copies.
   *(Done: `tests/test_lib_sourcing.py`.)*
4. **Fold `manager.sh` onto the same libs** (OVNode's `manager.sh` also duplicates four
   functions the allowlist never covered: `check_root`, `compose_file`, `has_systemd`,
   `is_docker_node`).
5. **Cut the flags**, and converge the subcommand names and help text with them, behind
   one deprecation release: warn, then remove. The only breaking change; own release.
6. **Claim key** for the panel owner account.
7. **Add `restore` and `completion`**, and the script-commit line.
8. **Trim the cards.**

Steps 2–4 are the structural core and are independently verifiable.

## Done when

- Neither repo defines a function in two files; no parity test is needed to say so.
- One code path per setting — an unattended run and an equivalent interactive run
  produce identical configuration, asserted by a test rather than reviewed.
- Three flags per installer, and every flag the parser accepts appears in `--help`.
- No plaintext owner password exists anywhere at install time, and no credential can be
  lost by closing a terminal.
- No read-only command can report a value it failed to read: an unreadable `.env` is an
  error naming the fix, never a default that looks like data.
- Every subcommand name means the same thing in both repos.
- OVNode's CI fails a broken installer (done — `7d78083`).
