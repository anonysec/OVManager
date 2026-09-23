# OVManager and OVNode TUI redesign plan

> Design proposal only. No shell behavior is changed by this document.

## Decision

The installer and manager remain separate programs, but use one visual language.

| Project | Setup command | Management command | Short alias |
|---|---|---|---|
| OVManager | `install.sh` | `ovmanager` | `ovm` |
| OVNode | `install.sh` | `ovnode` | `ovn` |

The long and short management commands are aliases of the same executable. The installer owns first installation only. After installation, routine operations belong to `ovm` or `ovn`.

The normal host installation is shown simply as **Install**. Docker is the exceptional option and is named explicitly.

## Design principles

1. **One numbered menu dialect.** Every screen uses the same header, spacing, numbering, prompt, Back, and Exit behavior.
2. **Simple language first.** Avoid systemd, runtime, Compose, ACME, PEM, and URLPATH unless an advanced/error screen truly needs them.
3. **Safe defaults.** Enter accepts the recommended non-destructive action. Destructive actions never become the default.
4. **No hidden configuration questions.** Fresh setup generates the password and private URL path. Both are changed later in the web UI.
5. **One screen, one purpose.** Setup, service control, backups, security, and recovery use separate screens.
6. **Commands remain first-class.** Every menu operation maps to a documented noninteractive command.
7. **Works everywhere.** ANSI color improves the display but is not required. Plain terminals receive the same words and choices.
8. **Consistent across projects.** OVManager and OVNode use the same positions and terms where operations match.

## Shared visual system

### Header

```text
OVManager Setup                                      v1.2.8
────────────────────────────────────────────────────────────
```

or:

```text
OVManager                                            v1.2.8
Running · Healthy
────────────────────────────────────────────────────────────
```

OVNode mirrors this exactly:

```text
OVNode                                               v1.1.0
Running · Connected
────────────────────────────────────────────────────────────
```

### Symbols and colors

| Meaning | Symbol | Color |
|---|---:|---|
| Success/healthy | `✓` | Green |
| Current work | `→` | Orange/cyan |
| Warning | `!` | Yellow |
| Failure | `✗` | Red |
| Inactive/metadata | `·` | Gray |

Color must never be the only indication. Disable it when output is not a TTY or `NO_COLOR` is set.

### Menu format

```text
1. First action
2. Second action

0. Exit

Select [1]:
```

Rules:

- Use `1.` consistently; do not mix `1)`, tags, and words.
- Keep labels under 30 characters when possible.
- Put descriptions only where the choice is not self-explanatory.
- Highlight the recommended item with text, not color alone.
- `0` means Exit on a top-level screen and Back on a submenu.
- Invalid input explains the valid range and asks again; it never silently selects item 1.
- Ctrl+C exits with code 130 and prints `Cancelled. No changes were made.` when true.

### Confirmation format

Normal confirmation:

```text
Install OVManager now? [Y/n]:
```

Risky confirmation:

```text
Remove OVManager? Data will be kept. [y/N]:
```

Destructive confirmation:

```text
This permanently deletes panel data and backups.
Type ERASE to continue:
```

## OVManager installer TUI

### Fresh server

```text
OVManager Setup                                      v1.2.8
────────────────────────────────────────────────────────────

1. Install              Recommended
2. Install with Docker

0. Exit

Select [1]:
```

Required wording is exactly **Install** and **Install with Docker**. Do not display implementation terminology such as “standard runtime” or “systemd service” on this screen.

### Behavior

- `1` or Enter installs the verified prebuilt release as a host service.
- `2` installs the published container image; it never builds locally.
- Both choices generate a random owner password and random private URL path.
- The normal flow asks no credential or URL-path questions.
- If requirements are missing, explain the issue after selection. Do not silently switch installation type.
- A flagless noninteractive run exits with instructions; `--yes` selects Install and `--docker --yes` selects Install with Docker.

### Review screen

```text
Review installation
────────────────────────────────────────────────────────────

Installation   Install
Version        1.2.8
Port           2095
Security       Encrypted connection
Data           /var/lib/ovmanager

1. Continue
2. Change port

0. Cancel

Select [1]:
```

For Docker, `Installation` reads `Install with Docker`. The generated password and private path are not shown before installation and are not editable here.

### Progress screen

```text
Installing OVManager
────────────────────────────────────────────────────────────

✓ Server checked
✓ Release verified
→ Starting OVManager
· Checking panel

Please wait…
```

Use five stable phases:

1. Check server
2. Download and verify
3. Configure
4. Start
5. Verify

Detailed command output belongs in a private log. A failed step prints the useful final error lines and log location.

### Success screen

```text
✓ OVManager is ready
────────────────────────────────────────────────────────────

Open       https://203.0.113.10:2095/a8f32c91/
Username   admin
Password   X7nK4pQ9vT2mL8sR6wDz

Save these details now. The password is shown only here.
The password and private URL can be changed in the web UI.

Manage this server later with: ovm
```

Do not place the OVNode installation command in this primary card. The panel onboarding flow should guide the user to add a node.

### Existing installation

```text
OVManager Setup                                      v1.2.8
Already installed · Healthy
────────────────────────────────────────────────────────────

1. Open management menu
2. Update
3. Repair
4. Uninstall

0. Exit

Select [1]:
```

Item 1 hands off to `ovm`. Installer code should not duplicate all management operations.

## OVManager management TUI

### Main menu

```text
OVManager                                            v1.2.8
Running · Healthy
────────────────────────────────────────────────────────────

Panel     https://203.0.113.10:2095/a8f32c91/
Backup    2 days ago
TLS       Valid for 3648 days

1. Status
2. Service
3. Logs
4. Update
5. Backups
6. TLS certificate
7. Diagnostics and repair
8. Recovery
9. Uninstall

0. Exit

Select [1]:
```

The three summary lines are best-effort and must render quickly. Slow network checks happen only after selecting Status or Diagnostics.

### Service submenu

```text
Service
────────────────────────────────────────────────────────────

Status: Running

1. Start
2. Stop
3. Restart

0. Back

Select [3]:
```

Stop defaults to No when confirmed. Restart may default to Yes.

Update staging, verification, automatic failover, reboot recovery, and manual rollback are specified in [update-failover-redesign.md](update-failover-redesign.md).

### Backups submenu

```text
Backups
────────────────────────────────────────────────────────────

Latest: /var/backups/panel-20260920-120000.tar.gz
Age:    2 days

1. Back up now
2. Automatic backups
3. Restore a backup

0. Back

Select [1]:
```

Restore displays candidates with date, size, and version, then requires explicit confirmation. Backup creation, scheduling, offsite copies, transactional restore, and recovery behavior are specified in [backups-https-redesign.md](backups-https-redesign.md).

### HTTPS certificate submenu

The certificate screen uses beginner-facing **HTTPS certificate** terminology and offers Automatic, Temporary, and Existing certificate flows. Validation, renewal, atomic activation, and rollback behavior are specified in [backups-https-redesign.md](backups-https-redesign.md). The existing `tls` command remains only as a temporary compatibility alias for the planned `https` command namespace.

### Diagnostics and repair

```text
Diagnostics and repair
────────────────────────────────────────────────────────────

1. Run diagnostics
2. Repair installation
3. Roll back last update

0. Back

Select [1]:
```

Diagnostics never changes state. `ovm doctor --fix` applies only allowlisted safe repairs and verifies them afterward. Repair lists proposed changes before applying them. Rollback identifies the exact snapshot and preserves current data. The complete doctor, auto-start, operation-locking, multi-node, error-handling, and disaster-recovery design is in [operations-recovery-redesign.md](operations-recovery-redesign.md).

### Recovery

```text
Recovery
────────────────────────────────────────────────────────────

1. Show panel address
2. Generate a new password
3. Generate a new private URL

0. Back

Select [1]:
```

Recovery actions generate secure random values. The TUI should not invite users to type secrets into command arguments.

## OVNode TUI counterpart

OVNode should follow the same information architecture, with node-specific wording.

### Installer

```text
OVNode Setup                                         v1.1.0
────────────────────────────────────────────────────────────

1. Install              Recommended
2. Install with Docker

0. Exit

Select [1]:
```

### Manager

```text
OVNode                                               v1.1.0
Running · Connected
────────────────────────────────────────────────────────────

VPN        Running
Panel      Connected
Clients    14 online

1. Status
2. Service
3. Logs
4. Update
5. Backups
6. TLS certificate
7. Diagnostics and repair
8. Network settings
9. Uninstall

0. Exit

Select [1]:
```

Matching operations use matching menu numbers wherever practical. Item 8 differs intentionally: Recovery for the panel and Network settings for a node.

## Command mapping

Menus are wrappers around stable commands, not separate implementations.

### OVManager

```text
ovm status
ovm start | stop | restart
ovm logs [N|-f]
ovm update
ovm backup
ovm auto-backup
ovm tls
ovm doctor
ovm repair
ovm rollback
ovm recovery
ovm reset-password
ovm reset-urlpath
ovm uninstall
```

### OVNode

```text
ovn status
ovn start | stop | restart
ovn logs [N|-f]
ovn update
ovn backup
ovn tls
ovn doctor
ovn repair
ovn network
ovn uninstall
```

Interactive functions call the same action functions used by direct commands. This prevents behavior drift.

## Implementation architecture

Within each repository:

```text
install.sh          Setup state machine and bootstrap actions
manager.sh          Management commands and menus
lib/common.sh       Shared rendering, prompts, validation, and helpers
```

Add reusable local TUI functions to `lib/common.sh`:

```text
tui_header TITLE VERSION STATUS
tui_menu DEFAULT TAG LABEL ...
tui_confirm MESSAGE DEFAULT
tui_danger MESSAGE REQUIRED_TEXT
tui_progress_set PHASE STATE MESSAGE
tui_card TITLE KEY VALUE ...
tui_pause
tui_clear
tui_terminal_width
```

The installer must remain able to bootstrap safely. Either embed the minimal shared rendering functions in the downloaded entry script or download a versioned, checksum-verified installer bundle before sourcing modules. Never source an unverified remote script.

OVManager and OVNode should share a written UI specification and fixtures, but each repository keeps its own copy of runtime code. One project's installation must not depend on the other repository being online.

## `whiptail` policy

Prefer one predictable plain numbered TUI. `whiptail` may enhance rendering only if it preserves identical labels, defaults, cancellation, and test behavior.

Recommended first release: remove the behavioral distinction and use the plain TUI everywhere. This avoids:

- different keyboard behavior across servers;
- menu output that is difficult to snapshot-test;
- failures on narrow terminals;
- requiring a package only for presentation.

A future dialog renderer can sit behind the same TUI functions.

## Accessibility and terminal behavior

- Support widths from 60 columns; never assume Unicode box drawing is available.
- Detect UTF-8 before using `✓`, `→`, and `✗`; otherwise use `OK`, `>`, and `X`.
- Honor `NO_COLOR` and non-TTY output.
- Send interactive UI and progress to stderr so stdout remains available for JSON.
- Never clear the screen during direct commands or automation.
- Never clear scrollback; if clearing interactively, clear only the visible screen.
- Mask secrets in display and logs except the one-time success/recovery result.

## Error design

Every failure card answers four questions:

1. What failed?
2. Why, in plain language?
3. Were existing data and service preserved?
4. What exact command should be run next?

Example:

```text
✗ OVManager did not start
────────────────────────────────────────────────────────────

The service started but did not answer the health check.
Your existing data was not removed.

Details   /var/log/ovmanager/install-20260920-143200.log
Next      ovm doctor
```

## Delivery plan

### Phase 1 — Freeze words and behavior

- Approve the menu labels and numbering in this document.
- Define TTY/non-TTY, Enter, invalid input, Escape, Ctrl+C, and `0` behavior.
- Create snapshot fixtures for every screen at 60 and 100 columns.
- Reconcile current docs with the chosen command behavior.

### Phase 2 — Shared OVManager renderer

- Add testable TUI primitives to `lib/common.sh`.
- Make `install.sh` and `manager.sh` use the same renderer.
- Preserve all direct commands and exit codes.
- Add `NO_COLOR`, ASCII fallback, and terminal-width tests.

### Phase 3 — New OVManager installer flow

- Replace Express/Custom with `Install` / `Install with Docker`.
- Generate password and private path without prompting.
- Add Review, Progress, Success, and Existing Installation screens.
- Ensure noninteractive flags bypass all prompts.

### Phase 4 — New OVManager management flow

- Add status summary and grouped submenus.
- Add/finish `repair` while keeping `doctor` read-only by default.
- Route every menu item through its direct-command implementation.
- Add destructive-action and cancellation tests.

### Phase 5 — Apply specification to OVNode

- Port the renderer and screen fixtures into the OVNode repository.
- Keep common numbering and wording.
- Add node-specific Network settings and connection status.
- Run side-by-side usability review for `ovm` and `ovn`.

## Acceptance criteria

- A new user can install by running the script, pressing Enter, reviewing, and confirming.
- The first menu says exactly `Install` and `Install with Docker`; it contains no host-runtime terminology.
- Fresh setup never asks for a password or private URL path.
- `ovm`/`ovmanager` are identical, and `ovn`/`ovnode` are identical.
- Installer and manager screens share headers, menus, confirmations, and errors.
- Every interactive action has a direct command and uses the same implementation.
- Menu snapshots pass with color, `NO_COLOR`, UTF-8, ASCII, 60-column, and 100-column terminals.
- Noninteractive commands never wait for input.
- Destructive actions cannot be accepted by pressing Enter.
- OVManager implementation lands and stabilizes before the same specification is ported to OVNode.
