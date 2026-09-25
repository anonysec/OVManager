# Update failover redesign plan

> Design proposal only. No update behavior is changed by this document.

## Goal

An update should either finish with the new healthy version or automatically return to the previous healthy version. Existing data must never be silently discarded, and the operator must always be able to see what happened and continue recovery.

“Failover” here means **local update failover to the previous release**, not high availability across multiple panel servers.

## User experience

### Update screen

```text
Update OVManager
────────────────────────────────────────────────────────────

Installed     1.2.8
Available     1.2.9
Data backup   Today at 03:30 · Verified
Disk space    8.4 GB available

The panel may be unavailable for about one minute.
If verification fails, OVManager will return to 1.2.8.

1. Update now
2. View release notes
3. Choose version

0. Back

Select [1]:
```

If there is no recent verified backup, the TUI says a new safety backup will be created. The operator cannot disable the safety backup from the normal flow.

### Progress

```text
Updating OVManager
────────────────────────────────────────────────────────────

✓ Safety backup verified
✓ Release downloaded and verified
✓ New version prepared
→ Checking version 1.2.9
· Completing update

Please wait…
```

Stable phases:

1. Preflight
2. Safety backup
3. Download and verify
4. Stage
5. Activate candidate
6. Verify
7. Commit or fail over

### Success

```text
✓ Update completed
────────────────────────────────────────────────────────────

Previous     1.2.8
Current      1.2.9
Panel        Healthy
Database     Migrated and verified
Failover     1.2.8 kept for recovery
```

### Automatic failover

```text
! Update failed over safely
────────────────────────────────────────────────────────────

Version 1.2.9 did not pass its health checks.
OVManager returned to version 1.2.8.
The panel is healthy and existing data is available.

Failed step  Panel health verification
Details      /var/log/ovmanager/update-20260920-151500.log
Next         ovm update details

1. View error details
2. Run diagnostics
3. Retry update

0. Back
```

Use **failed over safely** only when the previous release and data have actually passed health checks. Otherwise show **Update recovery needs attention** and exact recovery commands.

## Transaction model

### Release slots

Keep releases separate from mutable data:

```text
/opt/ovmanager/
├── current -> releases/1.2.8-build-id
├── previous -> releases/1.2.7-build-id
├── releases/
│   ├── 1.2.8-build-id/
│   └── 1.2.9-build-id.staging/
└── install-state.json

/var/lib/ovmanager/          Persistent data
/var/lib/ovmanager/backups/  Verified data backups
```

The exact paths may differ, but these properties are required:

- releases are immutable after verification;
- the active pointer changes atomically;
- persistent data is never stored inside a release directory;
- only the current and configured number of previous releases are retained;
- a staging directory can never be mistaken for an active release.

For Docker, the equivalent slots are immutable image digests plus previous/current Compose state. Never use a floating `latest` tag as rollback identity.

### Update journal

Write a private, atomic state journal before each transition:

```json
{
  "run_id": "20260920-151500-ab12",
  "from_version": "1.2.8",
  "to_version": "1.2.9",
  "phase": "verify_candidate",
  "previous_release": "...",
  "candidate_release": "...",
  "safety_backup": "...",
  "database_changed": true,
  "writes_enabled": false,
  "attempt": 1
}
```

On restart or rerun, the updater reads the journal and resumes cleanup, completes verification, or restores the previous state. It must not begin an unrelated second update.

## Detailed flow

### 1. Preflight

- Detect the installed method and current immutable release identity.
- Reject concurrent update, restore, backup, or certificate activation operations.
- Check supported upgrade path and target version.
- Check free space for release, backup, extraction, and rollback.
- Confirm service manager/container engine availability.
- Check current panel health and record degraded pre-existing conditions separately.
- Fetch signed/checksummed release metadata before downloading artifacts.

A currently unhealthy panel should not be updated through the normal flow. Offer diagnostics or an explicit recovery update that preserves stronger warnings and logs.

### 2. Safety backup

- Create a new data backup even when scheduled backups exist, unless a very recent verified update-safety backup matches the current data generation.
- Verify bundle checksums and SQLite integrity.
- Record the backup ID in the update journal.
- Do not prune this backup through normal retention until the update is committed and the recovery window expires.

Remote-copy failure may warn but should not block when the local safety backup is verified. Local backup failure blocks the update.

### 3. Stage release

- Download the prebuilt archive or published container image.
- Verify checksum/signature and expected version/commit.
- Validate archive entries before extraction.
- Prepare dependencies and generated service configuration without changing the active release.
- Run offline smoke checks against the staged code.
- Never fall back to cloning or building source.

### 4. Prepare database safely

Database migrations are the hardest rollback boundary. Code rollback alone is unsafe when the database is no longer compatible.

Required policy:

- Every release declares minimum/maximum readable schema and whether rollback is supported.
- Migration steps declare whether they are backward-compatible.
- Before activation, clone the database into private staging and run migrations plus schema verification there.
- Keep the live panel on the old database while offline staging checks run.
- At cutover, block writes and stop background jobs.
- Create a final consistent database snapshot.
- Apply the already-tested migration path to the candidate data state.
- Do not re-enable writes until the candidate passes startup and health verification.

Because writes remain blocked during candidate verification, automatic failover can safely restore the final pre-update database snapshot without losing post-update user changes.

For large databases where copying exceeds the downtime budget, report the estimated requirement before confirmation. Do not silently choose an unsafe in-place path.

### 5. Activate candidate

- Put the panel in maintenance mode.
- Stop the old process cleanly with a bounded timeout.
- Atomically point service configuration at the staged release or candidate image digest.
- Start the candidate with writes still disabled.
- Keep old release files/image and service configuration intact.

### 6. Verify candidate

Checks occur locally and have strict timeouts:

1. process/container remains running;
2. `/health` returns the expected target version;
3. database schema reports compatible/current;
4. critical read-only queries succeed;
5. static frontend entry and one API route respond;
6. configured HTTPS certificate loads;
7. startup logs contain no migration or fatal errors.

Do not depend on public DNS or external network availability for the commit decision. Those are reported separately as post-update diagnostics.

Run checks for a short stabilization window rather than accepting one successful response immediately.

### 7. Commit

Only after verification:

- mark the candidate release current;
- re-enable writes and background jobs;
- remove maintenance mode;
- perform one final health check;
- mark the journal committed;
- retain previous release and safety backup for a recovery window;
- prune older releases only after commit;
- record an audit event.

### 8. Automatic failover

On candidate failure:

1. keep writes disabled;
2. stop the candidate with a bounded timeout;
3. capture a sanitized log tail and failure reason;
4. restore the final pre-update database snapshot if migration touched data;
5. atomically restore previous release/service configuration or image digest;
6. start the previous version;
7. verify process, version, schema, critical reads, and `/health`;
8. re-enable writes only after previous-version verification;
9. preserve failed candidate, journal, logs, and safety backup for diagnostics;
10. report either safe failover or manual-attention state.

Never repeatedly alternate releases. One update run gets one automatic failover attempt. If previous-version verification fails, stop the loop and enter recovery mode.

## Interruption and reboot recovery

A power loss or Ctrl+C can happen during any phase.

- Before activation: remove staging and leave the current service untouched.
- During write blocking/cutover: read the journal on boot and complete candidate verification or fail over.
- After candidate verification but before commit record: verify the running release and reconcile pointers rather than guessing.
- During failover: retry the idempotent recorded step, bounded by an attempt counter.
- After commit: clean stale staging without changing the current release.

Install a small recovery unit for host-service installations and an equivalent host-side recovery command for Docker. Recovery logic must not live only inside the potentially broken candidate container.

## Manual rollback

```text
Rollback update
────────────────────────────────────────────────────────────

Current      1.2.9
Previous     1.2.8
Installed    Sep 20, 2026 at 15:18
Database     Rollback compatible

This returns code and data to the state before the update.
Changes made since the update may be lost.

1. Roll back to 1.2.8

0. Cancel

Select [0]:
```

Manual rollback is available only while the retained database snapshot and release are compatible. If writes occurred after commit, state the exact data-loss window and require typing `ROLLBACK`.

If the migration is not rollback-compatible, disable one-click rollback and offer restore from the update safety backup through the standard guided restore flow.

## Update commands

```text
ovm update check [--json]
ovm update run [--version VERSION]
ovm update status [--json]
ovm update details [RUN_ID]
ovm update retry
ovm update rollback
ovm update cleanup
```

Compatibility:

- `ovm update` remains an alias of `ovm update run`.
- `ovm rollback` becomes an alias of `ovm update rollback`.
- The installer may implement low-level mechanics, but `ovm` is the public management interface.

JSON status includes `run_id`, `phase`, `from_version`, `to_version`, `candidate_health`, `writes_enabled`, `failed_over`, `rollback_health`, `safety_backup_id`, and sanitized error information.

## Docker-specific requirements

- Pull and inspect the target image before stopping the current container.
- Record the current immutable image digest, not only its tag.
- Generate candidate Compose configuration separately.
- Keep persistent volumes unchanged until database cutover.
- Health-check the candidate through a host-local endpoint.
- On failure, recreate from the recorded previous digest and configuration.
- Do not run rollback logic solely inside the application container.

## OVNode failover

Apply the same release-slot, journal, bounded-attempt, and immutable-image rules to OVNode.

Node-specific verification includes:

- agent API health and expected version;
- OpenVPN service health;
- existing server configuration parses successfully;
- forwarding/NAT state remains valid;
- panel connectivity is reported but does not alone decide local rollback when the panel/network is temporarily unavailable;
- no automatic PKI regeneration occurs during update or failover.

Failing over OVNode must not revoke or replace client certificates.

## Security and audit

- Update locks and journals are root-owned and private.
- Release paths and archive entries cannot escape managed directories.
- Logs redact credentials, URL path, tokens, keys, and environment secrets.
- Audit `update.start`, `update.activate`, `update.success`, `update.failure`, `update.failover.start`, `update.failover.success`, and `update.recovery_required`.
- Failed artifacts remain only for a bounded diagnostic period and are never executed again without fresh verification.

## Testing plan

Fault-inject every transition for both installation methods:

- download interruption and checksum/signature failure;
- malformed or path-traversing archive;
- insufficient disk before and during staging;
- dependency preparation failure;
- migration failure on staged and cutover databases;
- process crash before health response;
- wrong reported version;
- health timeout after one transient success;
- certificate loading failure;
- stop timeout;
- power loss at every journal phase;
- failover service-start failure;
- corrupted safety backup;
- Docker image missing after pull or previous digest unavailable.

Each test asserts the active version, database contents/schema, write state, service health, journal phase, retained artifacts, and operator message.

## Delivery plan

### Phase 1 — Compatibility contract

- Add schema compatibility metadata to releases and migrations.
- Define journal states and idempotent transitions.
- Define immutable release identity and retention.
- Freeze commands, JSON, TUI wording, and audit events.

### Phase 2 — Staging and slots

- Introduce release directories/current pointer for direct installations.
- Record immutable image digests and candidate Compose state for Docker.
- Stage and smoke-test before stopping the active service.

### Phase 3 — Database-safe cutover

- Add staged migration checks, write blocking, final safety snapshot, and candidate read-only verification.
- Keep update safety backups outside normal retention during the recovery window.

### Phase 4 — Automatic failover

- Implement journal-driven bounded failover and reboot recovery.
- Add clear safe-failover versus recovery-required outcomes.
- Add manual rollback compatibility and data-loss checks.

### Phase 5 — OVNode adoption

- Port the transaction engine and journal.
- Add OpenVPN/network-specific verification.
- Prove failover never regenerates or mutates VPN PKI.

## Acceptance criteria

- The old healthy release keeps running until staging succeeds.
- No update activates an unverified artifact.
- Writes remain blocked from final database snapshot through commit or completed failover.
- Candidate verification checks expected version, schema, critical reads, frontend, API, process stability, and certificate loading.
- Candidate failure automatically restores both compatible code and database state.
- A safe-failover message appears only after the previous version passes health checks.
- Automatic failover attempts at most once and cannot boot-loop.
- Reboot recovery is journal-driven and idempotent.
- Docker rollback uses immutable image digests.
- Manual rollback warns about or prevents post-update data loss.
- Update rollback and ordinary backups remain clearly separate in the UI.
