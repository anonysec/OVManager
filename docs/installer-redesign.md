# Beginner-first installer redesign

> Proposal only. This document defines the next installer experience before implementation.

## Goal

A first-time VPS owner should be able to install OVManager safely without knowing Docker, systemd, TLS, ports, or URL paths. The installer should make the recommended decisions, explain only the choices that matter, recover cleanly from failure, and finish with one obvious next action.

### Success criteria

- A normal install asks for no configuration: direct host setup, credentials, and the private URL path all receive safe defaults.
- Docker is selected explicitly with `--docker`; advanced choices never block the default path.
- No question uses unexplained terms such as `systemd`, `URLPATH`, `PEM`, or `ACME`.
- Before changing the machine, the user sees a short summary and can go back.
- A failed install prints the failed step, a useful reason, a log path, and one retry command.
- Re-running the same command is safe and offers repair/update rather than overwriting data.
- The final screen fits in one terminal and clearly separates URL, username, password, and next step.
- Noninteractive behavior remains stable and machine-readable.

## Problems to solve

The current installer already has important foundations: Express and Custom paths, secure defaults, masked password input, preflight checks, progress indicators, release archives, update snapshots, health checks, rollback, and JSON output. The redesign should preserve these.

The beginner experience is still harder than necessary:

1. Documentation and script behavior have drifted. The script describes a zero-question default and a separate `interactive` action, while the README describes a start menu and older long option names.
2. Host-service and Docker implementation details are not beginner decisions, not beginner decisions.
3. TLS, secret paths, public URLs, ports, and install sources are exposed too early.
4. Errors from hidden commands can lack enough context to fix the problem.
5. Installation, repair, update, and day-to-day management are split correctly, but the handoff is not always obvious.
6. The completion screen can give credentials, a node command, and operational advice at once, competing for attention.

## Proposed user journey

### 1. Welcome and environment check

The installer immediately displays:

```text
OVManager Setup

Checking this server...
✓ Supported Linux: Ubuntu 24.04
✓ 1.8 GB memory and 12 GB free disk
✓ Internet connection
✓ Port 2095 is available
```

Checks run before questions so the installer does not collect input and then fail on a basic requirement. Warnings explain impact and offer a safe action. Hard blockers stop before any machine changes.

### 2. Interactive start menu, direct installation by default

A flagless run attached to a terminal opens a short action menu:

```text
OVManager Setup

1. Install              Recommended for most VPS servers
2. Install with Docker  Use the published container image
3. Exit

Select [1]:
```

Pressing Enter chooses Install. This is an action/runtime choice, not a configuration questionnaire; credentials and the private URL path remain automatically generated.

A noninteractive run cannot display a menu. `--yes` therefore selects Install, while `--docker --yes` explicitly selects Docker:

```text
install.sh --yes             Install, no prompts
install.sh --docker --yes    Docker, no prompts
```

Docker is never an implicit fallback. If direct-install requirements such as systemd are unavailable, stop with a clear explanation and suggest rerunning with `--docker` only when Docker is usable. This prevents scripts from silently receiving a different deployment model.

When an installation already exists, the same flagless command shows an installation-aware menu instead:

```text
OVManager is already installed and healthy.

1. Open management menu
2. Update
3. Repair
4. Uninstall
5. Exit

Select [1]:
```

### 3. Generate access details

Recommended setup does not ask for credentials or a URL path. It generates both with a cryptographically secure random source:

- Username starts as `admin`.
- A strong random owner password is generated on every fresh install.
- A random scanner-hiding URL path is generated on every fresh install.
- Existing credentials and paths are always preserved during reruns, repairs, and updates.
- Port defaults to `2095`.
- Self-signed TLS is used unless a usable domain is deliberately configured later.
- The installer detects the public IP rather than asking for a public URL.

The password and URL path are displayed only in the final credentials card and machine-readable success result. They must never appear in process arguments, progress logs, or error output. Both can be changed after login in the web UI.

### 4. Advanced setup as grouped choices

Advanced setup uses short pages, not one long questionnaire:

1. **Runtime** — “Standard server service (recommended)” or “Docker container”.
2. **Network** — optionally override the default port.
3. **Secure connection** — self-signed, domain certificate, or existing certificate.

Credentials and the private URL path are not installer choices, even in Advanced setup; they are always generated and can be changed safely in the web UI.

Each screen includes one-line consequences. Certificate file paths are requested only after “existing certificate” is selected. Domain validation occurs immediately rather than at the end.

Every screen supports **Back**, **Continue**, and **Cancel**. The plain-terminal implementation can use `b`, Enter, and `q`; `whiptail` is an optional presentation layer, never a behavior dependency.

### 5. Review before changes

```text
Ready to install

Setup       Standard server service
Panel       https://203.0.113.10:2095/<private-path>/
Login       admin
Security    Encrypted with a self-signed certificate
Data        /var/lib/ovmanager (kept during normal uninstall)

1. Install now
2. Change settings
3. Cancel
```

The generated password and full private path should not be shown in process arguments or logs. The summary explains self-signed TLS in plain language: the browser warning is expected until a trusted domain certificate is added.

### 6. Installation progress

Use a fixed phase model:

1. Preparing server
2. Downloading OVManager
3. Writing configuration
4. Starting service
5. Verifying panel

Each phase has a current operation and a final checkmark. On interactive terminals, concise output is the default. Full command output goes to a private log such as `/var/log/ovmanager/install-YYYYMMDD-HHMMSS.log` with secrets redacted.

Do not hide the useful error tail. On failure:

```text
✗ Could not start OVManager

The service started but did not answer its health check within 30 seconds.
No existing installation or data was removed.

Details: /var/log/ovmanager/install-20260920-143200.log
Retry:   sudo ovm repair
Help:    https://github.com/anonysec/OVManager/blob/main/docs/troubleshooting.md
```

### 7. Completion and handoff

Keep the final card focused:

```text
✓ OVManager is ready

Open:      https://203.0.113.10:2095/<private-path>/
Username:  admin
Password:  <generated-password>

Save these details now. The generated password is shown only here.
Your browser may warn about the self-signed certificate; this is expected.

Next: open the panel and follow “Add your first VPN node”.
Manage this server later with: ovm
```

The node installation command belongs in the panel setup wizard or behind an explicit “Show node command” choice, not in the primary success card.

## Existing-install journey

A rerun detects state before parsing interactive install answers:

```text
OVManager 1.2.7 is already installed and healthy.

1. Open management menu
2. Update
3. Repair
4. Reconfigure access
5. Uninstall
6. Exit
```

### Repair

Add `repair` as an idempotent operation. It should:

- validate `.env` without printing secrets;
- restore missing service/Compose and CLI files;
- ensure expected ownership and permissions;
- reinstall locked dependencies when needed;
- restart and run the health check;
- never reset credentials, paths, certificates, or data unless explicitly requested.

### Uninstall

Use two separate actions:

- **Remove application** — keep data, certificates, and backups; default.
- **Erase everything** — display exact paths, require typing `ERASE`, create a final backup first, and clearly report where that backup is stored.

## Reliability design

### Transaction model

Treat installation and update as staged transactions:

1. Detect and validate environment.
2. Download into a temporary directory.
3. Verify checksum and expected archive contents.
4. Build/prepare without touching the active install.
5. Write secrets with restrictive permissions from creation time.
6. Snapshot the active code and configuration metadata.
7. Atomically activate the staged release where possible.
8. Restart and verify `/health` plus a local authenticated startup check.
9. Roll back code/service configuration if verification fails; never roll back or delete live data automatically.

### Interrupt handling

The `INT`, `TERM`, and error traps should know the active phase, remove staging files, restore service state when activation has started, and print the recovery command. Cleanup must not replace the original exit code.

### Logs and diagnostics

- Assign every run an ID and include it in the screen and log filename.
- Redact password, secret path, bot key, encryption key, and certificate private-key content.
- Add `ovm doctor` to report runtime, service, permissions, disk, port, certificate expiry, and health without changing state.
- Add `--verbose` for command output and `--quiet` for automation.

## Command-line contract

Keep human and automation interfaces deliberately separate:

```text
install.sh                         Interactive beginner flow
install.sh install --yes ...       Unattended install
install.sh update --yes
install.sh repair --yes
install.sh uninstall --yes
```

Keep the public surface intentionally small:

```text
install.sh                         Install from a verified release (default)
install.sh --docker                Docker install from a published image
install.sh update                  Update the detected installation
install.sh uninstall               Remove the application but keep data

--yes, -y                          Never prompt; accept safe defaults
--version VERSION                  Install or update to a specific release
--port PORT                        Override port 2095
--json                             Emit one machine-readable result on stdout
--verbose                          Show detailed diagnostics
```

Advanced configuration such as URL path and TLS mode should happen after installation through the panel or `ovm`, rather than expanding the bootstrap interface. Environment variables may support CI-only configuration where necessary, but every public variable must be documented and tested.

There is deliberately no source-build flag. The production installer consumes only official, verified artifacts: a prebuilt release archive for direct host installations and a published container image for Docker installations. Developers and fork maintainers build through the normal repository workflow:

```text
git clone https://github.com/OWNER/OVManager.git
cd OVManager
# follow the developer build instructions
```

This keeps Git, Node.js, npm, compilers, branch selection, and arbitrary repository execution out of the root installer. A failed artifact download must stop with a useful error; it must never fall back to cloning or building source.

The installer accepts no password or URL-path flags and no environment-variable equivalents. Fresh installs always generate them; updates and repairs always preserve them. Deprecated credential/path inputs should emit a warning during one compatibility release and then be removed.

### Output and exit codes

With `--json`, stdout contains exactly one JSON document; progress and warnings stay on stderr. Include:

- `ok`, `action`, `changed`, `version`, and `runtime`;
- `panel_url` and `owner_user`;
- generated password only when the installer generated it;
- `error_code`, `failed_phase`, `message`, `log_path`, and `rolled_back` on failure.

Stable exit codes:

- `0` success;
- `2` invalid arguments or cancelled interaction;
- `3` unsupported environment/preflight failure;
- `4` download/integrity failure;
- `5` activation/health failure (rollback attempted);
- `6` partial recovery requiring operator action.

## Implementation structure

The current single shell file works for curl bootstrap, but behavior should be divided internally into testable layers:

- `install.sh` — tiny bootstrap and release selection;
- `lib/common.sh` — output, prompts, redaction, filesystem helpers;
- `lib/preflight.sh` — detection and checks;
- `lib/install.sh` — staging and activation;
- `lib/update.sh` — snapshots and rollback;
- `lib/ui.sh` — recommended/advanced state machine;
- `manager.sh` — ongoing operations, including new `repair` and `doctor`.

Release archives include these files. The remote one-liner may download the matching installer bundle to a private temporary directory before execution. Source checkouts can invoke the same modules directly.

Define one configuration model (`runtime`, `port`, `path`, owner, TLS, source/version) and have prompts, environment variables, and CLI flags populate it. Validate it once. This prevents interactive and unattended paths from drifting.

## Delivery plan

### Phase 1 — Contract and consistency

- Reconcile README, help text, examples, environment variables, and actual behavior.
- Define the configuration model, terminology, JSON schema, and exit codes.
- Add golden tests for help, recommended flow, advanced flow, cancellation, and JSON.
- Preserve all existing flags as compatibility aliases.

**Done when:** every documented command is tested and every supported flag appears in generated help.

### Phase 2 — Beginner flow

- Implement environment-first welcome, automatic credential/path generation, grouped advanced pages, Back/Cancel, and review screen.
- Redesign the success card and move node details to an optional follow-up.
- Test with and without TTY and `whiptail`, including narrow 80-column terminals.

**Done when:** a clean supported VPS can complete an installation without answering configuration questions and without needing infrastructure vocabulary.

### Phase 3 — Failure experience

- Add run logs, redaction, phase-aware errors, cleanup traps, and actionable failure cards.
- Add `ovm doctor` and `ovm repair`.
- Add fault-injection tests for download, disk-full, permission, service, health timeout, interruption, and rollback failures.

**Done when:** every injected failure either leaves the previous healthy version active or clearly reports the one manual recovery action required.

### Phase 4 — Transactional activation

- Stage and verify releases before activation.
- Make direct and Docker activation follow the same transaction states.
- Preserve data independently from code rollback.
- Test update from the oldest supported version and interrupted updates.

**Done when:** install/update is idempotent, rollback is automatic, and rerunning after interruption converges to a healthy state.

### Phase 5 — Validation and release

- Run clean-machine matrices for supported Ubuntu/Debian versions, low-memory VPS, Docker-only environments, IPv4-only/IPv6-only where supported, occupied ports, and existing installs.
- Conduct five beginner usability sessions; record questions, mistakes, and time-to-login.
- Ship behind `OVM_INSTALLER_V2=1`, then make it default after one release while retaining `--legacy-ui` temporarily.

**Done when:** at least 90% of beginner testers reach the login screen without external help, median time-to-login is under five minutes on a normal VPS, and no test loses existing data.

## Out of scope

- Installing a VPN node automatically on the panel server.
- Replacing the shell installer with a compiled language.
- Adding reverse proxies or external databases.
- Making self-signed certificates appear browser-trusted.
- Changing panel application setup beyond the post-install handoff.

These can be separate projects after the installer contract and recovery path are dependable.
