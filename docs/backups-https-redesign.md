# Backups and HTTPS redesign plan

> Design proposal only. No application, installer, backup, or certificate behavior is changed by this document.

This plan extends the shared TUI in [tui-redesign.md](tui-redesign.md). It applies first to OVManager and later to OVNode using the same language and interaction rules.

## Goals

### Backups

- Make it obvious what is protected, where copies are stored, and whether recovery has been tested.
- Replace overlapping host and web schedules with one authoritative schedule.
- Make restore safe, previewable, and automatically reversible.
- Distinguish application data backups from code-update rollback snapshots.
- Show local and per-destination remote results separately.

### HTTPS

- Use **HTTPS certificate** in beginner-facing screens instead of mixing TLS and SSL terminology.
- Make certificate status understandable without requiring certificate knowledge.
- Make automatic trusted certificates the preferred post-install upgrade.
- Validate and stage every certificate before replacing the active one.
- Keep the currently working certificate when issuance, upload, activation, or restart fails.

## Naming decisions

Use these terms consistently:

| Use | Do not use in primary UI |
|---|---|
| Backups | snapshots, dumps |
| Update rollback | backup, restore |
| HTTPS certificate | TLS/SSL, PEM |
| Automatic certificate | ACME certificate |
| Temporary certificate | self-signed certificate |
| Existing certificate | custom key + cert |

Technical terms can appear in an Advanced details screen and logs.

## Backup model

### One user-visible backup system

The panel schedule becomes the single source of truth for scheduled backups. `ovm` reads and changes that same schedule; it must not create a second independent timer.

This resolves the current conceptual duplication between:

- the schedule managed in the web UI; and
- the separate host-level automatic-backup timer managed by `ovm`.

During migration, detect both schedules. If the host timer exists, show its settings and offer to import them into the panel schedule before disabling the old timer. Never disable an old schedule silently.

### Backup types

Expose two distinct concepts:

1. **Data backup** — user, node, settings, traffic/accounting, audit, and other persistent panel data required for recovery.
2. **Update rollback** — short-lived code snapshot created automatically before an update.

The Backups menu manages data backups only. Update rollback remains under **Diagnostics and repair**.

### Backup artifact

Use a versioned bundle rather than an unexplained tarball or bare database:

```text
ovmanager-backup-20260920-143200-v1.ovmbak
```

The bundle contains:

```text
manifest.json       Format version, app version, created time, instance ID
panel.db            Consistent SQLite backup
settings/           Required persistent settings not stored in SQLite
certificates/       Active certificate material when full recovery requires it
checksums.sha256    Integrity hashes for every included file
```

It must not contain:

- application source or frontend assets;
- caches, logs, temporary files, or update snapshots;
- generated release artifacts;
- plaintext credentials in the manifest;
- unrelated files found beside the data directory.

Certificate private keys and other secrets inside a bundle make it sensitive. Local bundles must be created as `0600`, inside a private directory. SSH transfer must use authenticated SSH with strict host-key checking; Telegram transfer must be encrypted before upload.

### Consistent creation

A backup operation should:

1. Check available disk space.
2. Create a consistent SQLite snapshot using SQLite's backup mechanism.
3. Copy required settings into a private staging directory.
4. Write the manifest and checksums.
5. Verify the staged bundle before publishing it.
6. Atomically rename it into the backup directory.
7. Copy to each configured remote destination.
8. Apply retention only after the new local bundle verifies successfully.
9. Record local and per-destination remote outcomes independently.

A failed remote copy must not mark the local backup as failed or delete it.

## Backups TUI

### Main screen

```text
Backups
────────────────────────────────────────────────────────────

Last backup    Today at 03:30 · Verified
Schedule       Daily at 03:30 · Keep 14
Local copies   14 · 428 MB
Remote copies  SSH + Telegram · Last copies succeeded

1. Back up now
2. View backups
3. Automatic backups
4. Remote copies
5. Restore

0. Back

Select [1]:
```

Possible status language:

```text
Never backed up
Verified
Local saved · Telegram failed
Failed · View details
Disabled
Not configured
```

Do not show raw paths in the summary unless no friendlier status is available.

### Back up now

```text
Back up now
────────────────────────────────────────────────────────────

This creates a verified copy of OVManager data.
The panel remains available during the backup.

1. Create backup

0. Back

Select [1]:
```

Progress:

```text
Creating backup
────────────────────────────────────────────────────────────

✓ Database copied
✓ Settings collected
✓ Backup verified
→ Copying remotely

Please wait…
```

Result:

```text
✓ Backup completed
────────────────────────────────────────────────────────────

Created    Today at 14:32
Size       31 MB
Stored     On this server
Remote     SSH + Telegram copied successfully
Verified   Yes
```

### View backups

```text
Available backups
────────────────────────────────────────────────────────────

1. Today 14:32       31 MB · v1.2.8 · Verified
2. Today 03:30       30 MB · v1.2.8 · Verified
3. Sep 19 03:30      30 MB · v1.2.7 · Verified

0. Back

Select:
```

Selecting one opens:

```text
Backup details
────────────────────────────────────────────────────────────

Created      Sep 20, 2026 at 14:32
Version      OVManager 1.2.8
Size         31 MB
Integrity    Verified
Remote       SSH + Telegram copied
Location     /var/lib/ovmanager/backups/...

1. Verify again
2. Download path
3. Restore this backup
4. Delete this backup

0. Back
```

Delete defaults to No. The newest verified backup should display a warning before deletion.

### Automatic backups

```text
Automatic backups
────────────────────────────────────────────────────────────

Status       Enabled
Schedule     Every day at 03:30
Retention    Keep 14 backups
Next backup  Tomorrow at 03:30

1. Enable or disable
2. Change schedule
3. Change retention
4. Run a test backup

0. Back
```

Use server-local time and display the timezone explicitly when editing:

```text
Server time zone: Europe/Berlin
Backup time [03:30]:
```

Retention accepts count first. A later version may support age-based retention, but do not expose both until behavior is well tested.

### Remote copies

Backups need somewhere outside the OVManager server. Support multiple destination types behind one **Remote copies** screen:

```text
Remote copies
────────────────────────────────────────────────────────────

SSH server    Connected · Last copy succeeded
Telegram      Connected · Last copy succeeded

1. SSH server
2. Telegram
3. Test all destinations
4. Copy latest backup now

0. Back
```

Local backup success and each remote destination are recorded independently. One failed destination must not hide successful copies to the others.

#### SSH server

```text
SSH server
────────────────────────────────────────────────────────────

Status       Connected
Destination  backup@example.com:/srv/backups/ovmanager
Last copy    Today at 03:31 · Succeeded

1. Configure destination
2. Test connection
3. Copy latest backup now
4. Disable

0. Back
```

Configuration is advanced. Explain that SSH key authentication is required. Never accept an SSH password as a command-line flag or store one in panel settings.

The connection test verifies destination syntax, host identity, authentication, remote-directory access, a small create/read/delete round trip, and available space when the remote system reports it.

#### Telegram

Telegram is a convenient secondary copy destination, not the only backup. Service availability, account access, bot permissions, retention, and upload limits are outside OVManager's control.

```text
Telegram backup
────────────────────────────────────────────────────────────

Status       Connected
Destination  Private chat · ending 4821
Last copy    Today at 03:31 · Succeeded
Encryption   Enabled

1. Connect Telegram
2. Test connection
3. Send latest backup
4. View last delivery
5. Disconnect

0. Back
```

Connection flow:

1. Reuse the configured OVManager Telegram bot when suitable, or accept a dedicated backup-bot token through a secret input—not a command argument.
2. Ask the owner to message the bot, then select/confirm the discovered private chat. Group destinations require an explicit warning and confirmation.
3. Send a small test document and require Telegram to return a successful message/document identifier.
4. Delete the test message when supported; otherwise tell the operator it remains in the chat.
5. Store the bot token encrypted using OVManager's existing secret-encryption mechanism and show only a redacted chat identifier.

Security rules:

- Telegram copies must be client-side encrypted before upload because backup bundles contain credentials and may contain certificate private keys.
- Generate a separate backup-encryption key; do not derive it from the Telegram bot token.
- Show the recovery key once and let the owner download/copy it. Do not send that key to the same Telegram chat.
- Use authenticated encryption and record algorithm/version metadata in a small outer manifest.
- Split only when the currently reported Bot API upload limit requires it; discover/configure the limit rather than hard-coding an assumption into the UI.
- Record Telegram `chat_id`, `message_id`, file identifier, encrypted size, checksum, and delivery time without logging the bot token or encryption key.
- A Telegram API success is **Delivered**, not **Verified**, until OVManager downloads the object, validates its encrypted checksum, and—during an explicit test—decrypts and verifies the bundle.

Telegram retention should be conservative. OVManager may delete messages it created when the API permits, but failure to delete remotely is reported and never treated as proof that the backup disappeared. Local metadata keeps enough information to retrieve known backup messages.

Restore adds another source:

```text
Restore backup
────────────────────────────────────────────────────────────

1. Choose a backup on this server
2. Enter a backup file path
3. Retrieve from SSH server
4. Retrieve from Telegram

0. Back
```

Telegram restore downloads the selected document, verifies the encrypted checksum, asks for the recovery key when it is not available locally, decrypts into a private staging directory, and then enters the normal transactional restore flow. Plaintext staging files are removed on success, failure, or interruption.

### Restore

Restore must be a guided transaction, not a single confirmation.

Step 1 — choose source:

```text
Restore backup
────────────────────────────────────────────────────────────

1. Choose a backup on this server
2. Enter a backup file path
3. Retrieve from SSH server
4. Retrieve from Telegram

0. Back
```

Step 2 — inspect before changing anything:

```text
Review restore
────────────────────────────────────────────────────────────

Created       Sep 19, 2026 at 03:30
Version       OVManager 1.2.7
Integrity     Verified
Compatibility Compatible with 1.2.8

The panel will be unavailable briefly.
A safety backup of the current data will be created first.

1. Restore

0. Cancel

Select [0]:
```

Restore is never the Enter default. The operation then:

1. verifies extension, structure, checksums, and SQLite integrity;
2. checks format and application-version compatibility;
3. checks free disk space;
4. creates and verifies a pre-restore safety backup;
5. blocks writes and stops background jobs;
6. restores into staging;
7. applies migrations to the staged database;
8. verifies schema and starts against the candidate data;
9. activates only after health checks pass;
10. automatically returns to the pre-restore state if any post-activation check fails.

Result:

```text
✓ Restore completed
────────────────────────────────────────────────────────────

Restored     Sep 19, 2026 at 03:30 backup
Migration    Completed
Panel        Healthy
Safety copy  pre-restore-20260920-150100.ovmbak
```

### Backup commands

Keep direct commands for automation:

```text
ovm backup create
ovm backup list [--json]
ovm backup verify FILE
ovm backup restore FILE
ovm backup delete FILE
ovm backup schedule show
ovm backup schedule enable --time HH:MM --keep N
ovm backup schedule disable
ovm backup remote list
ovm backup remote test [DESTINATION]
ovm backup remote push [DESTINATION] [FILE]
```

For compatibility, `ovm backup` may remain an alias of `ovm backup create` for one major version. Replace the separate `auto-backup` command with `backup schedule`, retaining a deprecated alias temporarily.

Machine-readable results include `backup_id`, `path`, `size`, `verified`, `local_ok`, per-destination `remote_results`, and error details. Secrets and private-key content never appear.

## HTTPS certificate model

### Installation default

Fresh installation creates a temporary certificate automatically. The success screen explains the expected browser warning and points to the web UI for switching to a trusted certificate.

Do not ask certificate questions during the normal installer flow.

### Certificate choices

The HTTPS menu offers three user concepts:

1. **Automatic certificate** — trusted certificate for a domain or eligible public server IP.
2. **Temporary certificate** — generated locally; encrypted but causes a browser warning.
3. **Existing certificate** — operator provides certificate and private-key files.

Automatic setup explicitly asks which address to secure:

```text
Choose certificate address
────────────────────────────────────────────────────────────

1. Domain name       Example: panel.example.com
2. This server IP    Use the detected public IP

0. Back
```

Domain and IP issuance are equal supported flows in OVManager, but capability is checked before promising success. IP certificates require a publicly routable eligible address plus support from the configured ACME client and certificate authority. If those requirements are unavailable, explain the exact blocker and retain the temporary certificate.

### Ownership

The panel web UI and `ovm` must use the same certificate service, metadata, paths, validation rules, and renewal state. Shell and backend must not independently implement different certificate lifecycles.

Preferred boundary:

- a single privileged local certificate helper owns files and service restart;
- the web API and `ovm` invoke that helper through a narrow validated interface;
- status is read from one metadata file plus the active certificate;
- every operation is auditable without logging private material.

## HTTPS certificate TUI

### Main screen

```text
HTTPS certificate
────────────────────────────────────────────────────────────

Status       Valid
Type         Automatic certificate
Name         panel.example.com
Expires      Dec 18, 2026 · 89 days
Renewal      Automatic · Next check tomorrow

1. Set up automatic certificate
2. Use temporary certificate
3. Use existing certificate
4. Renew now
5. View details

0. Back

Select:
```

Status states:

```text
Valid
Expires soon
Expired
Not active
Renewal failed
Certificate does not match address
```

Use **Expires soon** at 30 days by default. Automatic certificates may use a shorter threshold derived from their lifetime.

### Automatic certificate

```text
Automatic certificate
────────────────────────────────────────────────────────────

A trusted certificate removes the browser warning.
Your domain must point to this server.

Domain: panel.example.com
```

Preflight results:

```text
Checking domain
────────────────────────────────────────────────────────────

✓ Domain format is valid
✓ DNS points to this server
✓ Port 80 is reachable locally
✓ Certificate service is available

1. Request certificate

0. Cancel
```

DNS checks should show observed and expected addresses when they differ. A local port check cannot guarantee internet reachability, so wording must not claim that it can.

Issuance flow:

1. Validate the normalized domain and reject command-like input.
2. Resolve A/AAAA records and compare with detected public addresses.
3. Check challenge prerequisites and explain conflicts.
4. Request into a private staging directory.
5. Validate chain, hostname, dates, key match, and readable format.
6. Install atomically while preserving the previous pair.
7. Restart or reload the panel.
8. Verify the panel answers using the new certificate.
9. Restore the previous certificate automatically if activation fails.
10. Enable renewal only after successful activation.

Success:

```text
✓ Automatic certificate is active
────────────────────────────────────────────────────────────

Name       panel.example.com
Expires    Dec 18, 2026
Renewal    Automatic
Panel      Healthy
```

### Temporary certificate

```text
Use temporary certificate
────────────────────────────────────────────────────────────

The connection will be encrypted, but browsers will show a warning.
Use this for initial access or private networks.

Replace the current certificate? [y/N]:
```

Generate a new key rather than reusing an unknown existing key. Preserve the previous working pair until activation succeeds.

### Existing certificate

```text
Use existing certificate
────────────────────────────────────────────────────────────

Certificate file:
Private-key file:
```

Before confirmation, show validation:

```text
Certificate accepted
────────────────────────────────────────────────────────────

Names        panel.example.com, www.panel.example.com
Expires      Dec 18, 2026 · 89 days
Key match    Yes
Chain        Valid structure

1. Activate certificate

0. Cancel
```

Requirements:

- reject missing, unreadable, malformed, expired, or not-yet-valid certificates;
- reject mismatched private keys;
- reject symlinks and non-regular files where privileged path handling is involved;
- copy into the managed private directory instead of referencing arbitrary paths forever;
- write the key as `0600` and public chain as `0644`;
- never print or log private-key content.

### Renew now

Show the current type first. Automatic certificates can be renewed. Temporary certificates can be regenerated. Existing certificates cannot be renewed automatically; direct the operator to supply a replacement.

```text
Renew certificate
────────────────────────────────────────────────────────────

Current      Automatic certificate
Name         panel.example.com
Expires      12 days

1. Renew now

0. Back
```

If renewal fails, keep the current certificate active and report its remaining validity.

### Details

```text
Certificate details
────────────────────────────────────────────────────────────

Status       Valid
Type         Automatic certificate
Names        panel.example.com
Issuer       Let's Encrypt
Valid from   Sep 19, 2026
Expires      Dec 18, 2026
Fingerprint  SHA256:AB:CD:…
Key          RSA 2048
Files        Managed by OVManager
Last renewal Sep 19, 2026 · Succeeded
```

Do not display the private-key path in the beginner view. It may appear in `--verbose` diagnostics for root.

### HTTPS commands

Use one command namespace:

```text
ovm https status [--json]
ovm https automatic DOMAIN
ovm https temporary
ovm https existing --certificate FILE --key FILE
ovm https renew
ovm https details
ovm https test
```

Keep `ovm tls` as a compatibility alias that prints a deprecation notice on stderr and opens `ovm https`. Do not introduce a separate `ssl` command.

For unattended existing-certificate activation, file paths are acceptable, but inputs receive all regular-file/symlink/ownership checks. There should be no flags accepting private-key contents.

## OVNode alignment

OVNode uses the same Backups and HTTPS screen structures and command grammar:

```text
ovn backup ...
ovn https ...
```

Node backup contents differ and must be explicitly documented. A node bundle should include only the agent's persistent configuration and data required to reconnect/recover. OpenVPN PKI material is highly sensitive; its inclusion, permissions, and restore behavior require a separate threat-model review before implementation.

The node certificate screen should clearly distinguish:

- the HTTPS certificate used by the node API; and
- OpenVPN certificates used by VPN clients.

Never place both under one ambiguous “Certificates” action.

## Web UI alignment

The terminal and web interfaces should expose the same status and operations:

### Settings → Backups

- last result and next run;
- create, list, verify, download, delete, and restore;
- schedule and retention;
- SSH and Telegram destinations with connection tests;
- local and per-destination remote outcome history.

### Settings → HTTPS certificate

- current status, name, issuer, and expiry;
- automatic, temporary, and existing-certificate flows;
- renewal status and last error;
- activate/restart result.

Neither interface should maintain settings the other cannot see.

## Security and audit requirements

Audit these events without secrets:

```text
backup.create
backup.verify
backup.delete
backup.restore.start
backup.restore.success
backup.restore.rollback
backup.remote.success
backup.remote.failure
https.issue
https.activate
https.renew
https.rollback
```

Each event records actor, timestamp, result, artifact/certificate fingerprint where appropriate, and a sanitized reason on failure.

Rate-limit web-triggered backup, restore, issuance, and renewal operations. Use a process-wide operation lock so two restores or certificate activations cannot overlap.

## Delivery plan

### Phase 1 — Inventory and contract

- Document exactly which persistent files belong in OVManager and OVNode backups.
- Define `.ovmbak`/node equivalent manifest and compatibility rules.
- Choose the panel schedule as the single backup schedule.
- Define certificate metadata and privileged-helper contract.
- Freeze CLI grammar and JSON output.

### Phase 2 — Backup foundation

- Implement consistent versioned bundles, checksums, atomic publication, and verification.
- Add list/details/delete commands and API operations.
- Unify schedule state and migrate the legacy host timer with confirmation.
- Record local and per-destination remote outcomes independently.

### Phase 3 — Transactional restore

- Implement compatibility preflight and safety backups.
- Restore through staging, migrations, verification, activation, and rollback.
- Add interruption and fault-injection tests at every phase.
- Build matching TUI and web flows.

### Phase 4 — HTTPS certificate service

- Consolidate shell and backend certificate logic behind one service/helper.
- Add staging, validation, atomic activation, health verification, and rollback.
- Add automatic renewal status and failure reporting.
- Build matching `ovm https` and web flows.

### Phase 5 — OVNode adoption

- Threat-model node backup contents and VPN PKI handling.
- Port shared screen structure and commands.
- Keep API HTTPS and VPN-client certificate concepts separate.
- Run cross-project snapshot and recovery tests.

## Acceptance criteria

### Backups

- There is one visible schedule, editable from both web UI and `ovm`.
- Every completed backup is integrity-checked before retention deletes anything.
- Local success remains visible when any remote copy fails.
- Restore always creates a verified safety backup first.
- A failed restore returns automatically to the pre-restore data and health state.
- Backups and update rollback are never presented as the same feature.
- Secret-bearing artifacts are never group/world-readable.

### HTTPS

- Beginner screens consistently say HTTPS certificate.
- The active certificate is never replaced before the candidate passes validation.
- Failed activation restores the previous working certificate automatically.
- Domain, dates, key match, file type, and permissions are validated.
- Renewal failure never removes a still-valid active certificate.
- Web UI and TUI report the same type, expiry, renewal state, and last error.
- OVNode clearly separates API HTTPS from VPN-client certificates.
