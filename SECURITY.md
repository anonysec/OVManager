# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 2.0.x (post-reset) | yes |
| < 2.0.0 | no        |
| 2.1.x–2.4.x (pre-reset) | no |

Only the post-reset `2.0.x` line of OVManager is supported. Pre-reset releases (`2.1.0` through `2.4.6`) are legacy/archived and unsupported.
Always upgrade both together: panel `2.0.x` pairs with node `>= 2.0.0`.

## Reporting a vulnerability

**Do not open a public issue.** Use
[GitHub Private Vulnerability Reporting](../../security/advisories/new)
(Security tab → Advisories) or email the maintainer address listed on the
repository profile.

Include: affected version(s), steps to reproduce, and impact assessment.
You will get an acknowledgement within 7 days and a fix timeline within
30 days. We follow a 90-day disclosure policy after a fix is released.

## Scope

In scope: authentication/session handling, node API-key handling and
storage, subscription-link access control, installer privilege handling,
Telegram bot token handling.

Out of scope: DDoS/volumetric abuse, OpenVPN or EasyRSA upstream CVEs
(update those packages), social engineering, physical access.

## Threat model & secret storage

- **Owner-claim status**: Unauthenticated `GET /api/owner-claim` intentionally reveals whether the panel is claimable or recoverable (setup state). It exposes no credentials.
- **Secrets at rest**: Sensitive columns (`nodes.key` and `settings.bot_token`) are encrypted at rest with AES-256-GCM. The encryption key (`secret.key`) is stored in the data directory with strict `0600` permissions (read/write only by the service user/root), isolated from the SQLite database file.
- **Telegram backups**: Automatically redact all active session tokens, the Telegram bot token, and node API keys (`DELETE FROM sessions`, redacted keys). Even if a Telegram backup document is intercepted, it contains no usable secrets or credentials.
- **Offsite backups**: Encrypted with AES-256-GCM prior to transfer (`.db.enc`) so plaintext databases never transit or rest on remote storage unprotected.

## Node TLS verification & fallback

The panel strictly verifies each node's TLS certificate against its pinned certificate (`server_ca`). If verification fails, requests fail closed by default.

Only when `NODE_TLS_INSECURE_FALLBACK=true` is explicitly set in `.env` does the panel fall back to unverified TLS for self-signed nodes. Whenever this fallback is exercised, a prominent `CRITICAL` audit event (`node.tls_unverified`) is logged.

Mitigations:

- Use valid certificates with matching SANs on nodes so strict verification passes.
- Do not enable `NODE_TLS_INSECURE_FALLBACK` in production environments.
- Check the audit log for `node.tls_unverified` events and investigate.

## Hardening checklist (production)

- Keep `secret.key` out of offsite/Telegram backup destinations; encrypted backups are useless without it, and storing it beside them defeats encryption.

- Keep the owner claim key and node API keys private; never reuse keys across hosts.
- Maintain a non-empty `URLPATH` prefix (e.g. `/dashboard/` or custom secret path).
- Serve behind TLS with Let's Encrypt or validated certificates.
- Set `TRUSTED_PROXY=true` only when running behind a dedicated reverse proxy on loopback/private CIDR, and configure `TRUSTED_PROXY_CIDRS`.
- Regularly back up the database and `secret.key`, but store `secret.key` separately from encrypted backups (`.db.enc`); a backup alone must not be decryptable. Verify restores.

## Release signing trust model

- **No signed releases any more.** Releases (`release.yml`) and dev builds (`dev-release.yml`) publish bare binaries only — no `.sha256`/`.sig`/`.minisig` artifacts and no Ed25519 signing step.
- `install.sh`, `ovnode.sh` and the `ovmanager update` CLI therefore install/verify whatever the release publishes as-is; there is no signature, checksum or attestation path to validate.
