# Privacy

OVManager is self-hosted. The project does not receive installation data merely because you install or run the software, and the software includes no project telemetry or analytics by default.

## Operator responsibility

The server operator decides how and why panel and VPN-related data is processed and is responsible for applicable privacy, retention, user-notice, provider, and cross-border-transfer requirements. This document describes software behavior; it is not legal advice.

## Data stored by OVManager

Depending on enabled features, the panel stores administrator accounts and sessions, VPN-user records, node addresses and credentials, traffic/usage history, security audit events, settings, backup metadata, and Telegram configuration. Logs may contain IP addresses and operational identifiers. HTTPS and node private keys are stored only in managed private locations.

## External services

No optional external integration is enabled merely by installing OVManager. When configured by the operator:

- OVNode servers receive configuration required to manage users and return health/usage information.
- Telegram receives selected notifications or encrypted backup files and delivery metadata.
- An SSH backup server receives backup files.
- Certificate authorities receive domain or public-IP validation requests and related technical metadata.
- Release hosting receives ordinary download/update requests.

Each external service has its own terms and privacy practices. Telegram notifications and Telegram backup delivery are separate choices.

## Security and retention

Secrets are excluded from normal diagnostic output and should never be included in support reports. Backup files can contain sensitive data and must be protected. Operators control live-data deletion and configured retention; deletion from the live database does not immediately remove data from retained backups, which expires according to backup retention.

## Operator controls

Operators can disable integrations, revoke sessions and credentials, remove users/nodes, configure backup retention, and uninstall or purge the panel. Before serving end users, operators should publish their own privacy notice describing their actual configuration, legal basis, retention, recipients, and user rights.

## Changes

Material changes to project-hosted data collection, telemetry, or external integrations must be documented here before release and must not be silently enabled.
