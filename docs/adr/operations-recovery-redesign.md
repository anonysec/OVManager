# Diagnostics, repair, locking, and disaster recovery plan

> Design proposal only. No runtime behavior is changed by this document.

## 1. Doctor command

Follow the simple diagnostic pattern requested from Hermes Agent:

```text
ovm doctor          Diagnose and recommend; never change state
ovm doctor --fix    Apply only approved safe repairs, then re-check
ovm doctor --json   Stable machine-readable report
ovm doctor --deep   Include slower local and multi-node checks
ovm dump            Create a redacted, local support report
```

`doctor` and `doctor --fix` must use the same check registry. Each check defines an ID, scope, severity, timeout, evidence, remediation text, whether an automatic fix exists, and a verification function.

### Output

```text
OVManager Doctor
────────────────────────────────────────────────────────────

✓ Installation       Release 1.2.8 is complete
✓ Configuration      Valid · secrets protected
✓ Service            Running · starts automatically
✓ Panel health       Healthy · 42 ms
✓ Database           Integrity OK · schema current
! Backups             Telegram copy failed
✓ HTTPS certificate  Valid for server IP · 63 days
! Nodes               1 of 8 nodes unavailable
✓ Disk                31% used · 18 GB available

2 warnings · 0 errors
Run `ovm doctor --fix` to repair 1 safe issue.
```

The normal command completes quickly and uses bounded checks. `--deep` may verify a backup sample, remote backup destinations, public certificate presentation, update artifacts, and every configured node.

### Core checks

- installed release identity, expected files, checksum/manifest, and incomplete update journal;
- configuration syntax, required values, secret strength, ownership, and permissions;
- service installed, running, enabled at boot, restart count, and recent fatal logs;
- local health endpoint, expected version, frontend asset, and critical read-only API path;
- SQLite integrity, schema version, migration drift, writable data directory, and restore lock;
- disk space/inodes, backup age/integrity, SSH and Telegram remote-copy status;
- HTTPS certificate key match, address match, validity, chain, active presentation, and renewal state;
- operation lock ownership and stale-journal state;
- update current/previous release consistency;
- time synchronization because certificates, sessions, and schedules depend on correct time;
- required tools only for enabled features;
- firewall listening state without changing provider firewalls.

### Multi-node checks

OVManager supports OVNode on separate servers. Doctor must diagnose them through the existing authenticated node API, never assume local processes and never SSH into nodes.

Normal `ovm doctor` reports cached/quick summary:

```text
Nodes    7 healthy · 1 unavailable
```

`ovm doctor --deep` checks each node with bounded parallelism:

- DNS resolution and configured address;
- TCP/API reachability and authenticated health;
- identity/fingerprint matches the registered node;
- OVNode and OpenVPN status;
- panel/node API compatibility;
- certificate validity and address match;
- clock skew;
- disk pressure;
- last traffic synchronization;
- agent update availability;
- reported forwarding/NAT health when exposed by OVNode.

One node timeout must not block all results. Output groups failures and returns a partial-health result, not “panel broken.” Fixes that alter a remote node require a separate authenticated node action and explicit confirmation; `doctor --fix` must not silently change remote networking, OpenVPN, firewall, or PKI.

### Safe `--fix` policy

Automatically fix only actions that are deterministic, reversible, and do not alter user networking or credentials:

- restore expected file ownership and restrictive permissions;
- reinstall missing service unit from the verified active release;
- reload the service manager;
- enable automatic start when the configured policy says enabled;
- restart a stopped service after configuration validation;
- remove abandoned staging files proven not active;
- prune expired logs or old releases while preserving required recovery copies;
- clear a stale lock only after proving its owner is gone and journal recovery is complete;
- resume or fail over an interrupted update according to its journal.

Never auto-fix:

- database corruption by deleting or replacing data;
- backup restore;
- certificate identity/domain/IP choices;
- passwords, URL paths, API credentials, bot tokens, or encryption keys;
- remote-node firewall, routes, NAT, OpenVPN PKI, or client certificates;
- uninstall/purge;
- an ambiguous operation journal.

`doctor --fix` prints the proposed safe fixes, asks once in a TTY, applies them one by one, and re-runs affected checks. `--yes` is required for unattended changes. A failed fix does not prevent independent later fixes, but dependency-aware fixes are skipped with an explanation.

### Exit codes

```text
0  Healthy
1  Internal/usage failure
2  Warnings only
3  One or more errors
4  Repairs applied; now healthy
5  Repairs incomplete; operator action required
```

JSON should additionally contain the exact severity counts so automation does not need to infer meaning from text.

## 2. Service and automatic start

Add automatic-start control to the Service menu:

```text
Service
────────────────────────────────────────────────────────────

Status       Running
Auto start   Enabled
Started      3 days ago
Restarts     0 unexpected

1. Start
2. Stop
3. Restart
4. Enable automatic start
5. Disable automatic start

0. Back
```

For a host installation, this maps to the OVManager systemd unit:

```text
ovm service enable
ovm service disable
ovm service start|stop|restart|status
```

Rules:

- installation enables automatic start by default;
- enabling validates the unit before calling `systemctl enable`;
- disabling auto start does not stop the currently running panel;
- stopping the panel does not disable auto start;
- service actions have bounded timeouts and post-action verification;
- `doctor` reports running and enabled states separately;
- do not modify unrelated systemd units or global settings.

For Docker, show the same user concept and manage only OVManager's container restart policy. The UI need not expose Docker terminology unless details are requested.

OVNode follows the same service interface on each node. OVManager can display remote node auto-start state if OVNode reports it, but changing it is a node-scoped authenticated action.

## 3. Repair command

`ovm repair` is a guided, broader operation; it is not an alias of `doctor --fix`.

```text
Repair installation
────────────────────────────────────────────────────────────

1. Repair service and files
2. Recover interrupted update
3. Rebuild application environment
4. Repair database from verified backup
5. Reconnect management command

0. Back
```

Flow:

1. Run doctor and identify repair candidates.
2. Show the exact proposed changes and whether restart/downtime is needed.
3. Create a verified safety backup before data-affecting work.
4. Acquire the operation lock.
5. Apply staged changes.
6. Verify panel and database health.
7. Roll back changed files/data when verification fails.
8. Release the lock and write an audit event.

Repair preserves credentials, private URL path, certificates, data, backup configuration, and node registrations unless the selected recovery procedure explicitly concerns one of them.

## 4. Operation locking

All state-changing maintenance operations share one persistent coordinator:

```text
backup.create
backup.restore
update
repair
https.activate
https.renew
recovery.rotate-secret
uninstall
```

A lock record contains operation ID, type, PID/container identity, actor, start time, heartbeat, journal path, cancellability, and current phase. The record is root-owned/private and written atomically.

### Conflict policy

- Read-only status, doctor, logs, and backup listing remain available.
- One exclusive operation runs at a time unless a compatibility matrix explicitly proves two are safe.
- Restore, update activation, repair, certificate activation, and uninstall are always exclusive.
- Scheduled backup skips with a recorded reason when an exclusive operation owns the lock; it never queues indefinitely.
- Web UI, TUI, background scheduler, and startup recovery use the same coordinator.

### Busy screen

```text
Another operation is running
────────────────────────────────────────────────────────────

Operation    Update to 1.2.9
Started      14:32 · 3 minutes ago
Phase        Verifying new version
Run ID       update-ab12

1. View progress
2. Request safe cancellation

0. Back
```

Cancellation is cooperative and allowed only at declared safe points. Never kill a restore or migration blindly.

### Stale locks

A missing PID alone does not prove a lock is stale. Recovery checks the journal, active service/container, current release pointer, database write state, and heartbeat. It then resumes, fails over, or reports manual recovery. `doctor --fix` may clear the lock only after this reconciliation proves no operation remains active.

## 5. Full disaster recovery

This covers loss of the original server, not an ordinary in-place restore.

### Recovery prerequisites

Encourage owners to keep separately:

- at least one encrypted remote backup (SSH and/or Telegram);
- backup recovery key stored outside the server and outside the same Telegram chat;
- current panel domain or IP information;
- OVNode addresses and identity fingerprints;
- a copy of this recovery procedure.

### Clean-server flow

```text
OVManager Setup
────────────────────────────────────────────────────────────

1. Install
2. Install with Docker
3. Recover from backup

0. Exit
```

Recovery asks for installation type, then backup source:

```text
Recover OVManager
────────────────────────────────────────────────────────────

1. Backup file on this server
2. SSH backup server
3. Telegram backup

0. Cancel
```

Transaction:

1. Check supported OS/resources and establish private staging.
2. Retrieve encrypted backup without logging credentials or keys.
3. Ask for recovery key through masked input when needed.
4. Verify encrypted object, decrypt, validate bundle checksums and manifest.
5. Determine the compatible OVManager release from backup metadata.
6. Download and verify that release; never clone source.
7. Restore/migrate data in staging.
8. Detect new public IP/domain and identify certificate/address mismatch.
9. Start privately and run database, API, frontend, and certificate checks.
10. Activate only after verification.
11. Show node reconnection status and guided follow-up.
12. Securely clean plaintext staging and write a local recovery report.

### Multi-node recovery

Nodes remain on separate servers and should continue serving VPN clients when the panel is lost. Recovery must not reinstall, reset, or regenerate OVNode automatically.

After panel restore:

```text
Reconnect nodes
────────────────────────────────────────────────────────────

✓ de-1     Identity verified · Connected
✓ us-1     Identity verified · Connected
! sg-1     Address changed · Action required
✗ old-1    Identity mismatch · Not trusted
```

Rules:

- preserve registered node IDs, fingerprints, and credentials from backup;
- reconnect through the authenticated OVNode API;
- treat identity mismatch as a security error, never “accept automatically”;
- allow address updates only after fingerprint confirmation;
- rotate a node credential individually when recovery requires it;
- do not regenerate OpenVPN CA/server/client certificates;
- show partial success when some nodes are offline;
- avoid fan-out overload with bounded concurrency and retry backoff.

### Address and HTTPS recovery

The recovered panel can use either a domain or public IP certificate:

- if the old domain still points to the new server, renew/activate its automatic certificate;
- if using a new domain, guide DNS update and request a new certificate;
- if using a public IP, check IP-certificate eligibility and request it when supported;
- otherwise activate a temporary certificate and clearly show the expected browser warning;
- keep restored certificate files only when they match the selected address and remain valid.

### Recovery completion

```text
✓ OVManager recovered
────────────────────────────────────────────────────────────

Panel       Healthy
Data        Restored and verified
HTTPS       Temporary certificate · action recommended
Nodes       7 connected · 1 needs attention
Backups     Telegram connected · SSH needs new host approval

Next        Open the panel and review Recovery status
```

## 6. Error messages and handling

### Error object

Every layer uses a structured internal error:

```text
code          Stable identifier, e.g. UPDATE_HEALTH_TIMEOUT
title         Short user-facing summary
message       Plain-language cause
operation_id  Correlation/run ID
phase         Failed phase
severity      warning | error | critical
retryable     true/false
data_safe     true/false/unknown
next_action   Exact command or UI action
details       Sanitized technical context
cause         Internal chained exception, logs only
```

API responses include safe fields and a correlation ID. Logs contain technical details with the same ID. Secrets, credentials, URL paths, tokens, backup keys, and private keys are always redacted.

### User-facing format

```text
✗ Could not activate the certificate
────────────────────────────────────────────────────────────

The new certificate was valid, but the panel did not restart.
The previous certificate was restored and the panel is healthy.

Run ID      https-ab12
Next        ovm doctor
Details     /var/log/ovmanager/operations/https-ab12.log
```

Every operational error answers:

1. What failed?
2. What state is running now?
3. Is data safe?
4. Was rollback/failover completed?
5. What should the operator do next?
6. Where are sanitized details?

### Handling rules

- Catch errors at operation boundaries, not with broad silent `except` blocks.
- Preserve the original cause while cleanup errors are attached separately.
- Time out all network, process, node, Telegram, SSH, DNS, and certificate operations.
- Retry only idempotent operations, with bounded exponential backoff and jitter.
- Do not retry authentication, validation, identity mismatch, or destructive operations automatically.
- Partial multi-node failures return per-node results and do not erase successes.
- Database transactions roll back on exceptions; filesystem changes use staging and atomic replacement.
- Cleanup runs on success, failure, interruption, and reboot recovery without hiding the original result.
- Background failures become visible in status, audit history, and configured notifications.
- Stable error codes are documented and tested; user text may improve without breaking automation.

## Delivery plan

1. Define check registry, structured errors, operation journal, locks, and stable JSON/error codes.
2. Implement read-only `doctor`, `dump`, and service auto-start status.
3. Implement safe `doctor --fix` and verify-after-fix behavior.
4. Route update, restore, backup, HTTPS, repair, and uninstall through the operation coordinator.
5. Implement guided repair and stale-operation recovery.
6. Implement clean-server disaster recovery and remote-backup retrieval.
7. Add multi-node deep diagnostics and post-recovery reconciliation.
8. Port the shared doctor/error/lock design to OVNode.

## Acceptance criteria

- `ovm doctor` never changes state.
- `ovm doctor --fix` applies only allowlisted safe repairs and rechecks each result.
- Auto start is enabled by default and controllable without stopping the running service.
- The normal doctor is fast; deep node checks are bounded and parallel.
- Remote nodes are diagnosed through OVNode APIs, not local assumptions or SSH.
- All maintenance entry points share one persistent lock and journal.
- Interrupted operations recover idempotently after reboot.
- Every error includes state/data-safety outcome, run ID, and next action.
- A clean server can recover from encrypted SSH or Telegram backup.
- Recovery preserves node identities and never regenerates VPN PKI.
