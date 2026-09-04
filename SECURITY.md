# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 2.x     | yes       |
| < 2.0   | no        |

Only the latest `2.x` release of OVManager + OVNode is supported.
Always upgrade both together: panel `2.x` requires node `>= 2.0` (sync API).

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

## Hardening checklist (production)

- Install with random secrets (`ADMIN_PASSWORD`, `BOT_ENCRYPT_KEY`,
  `NODE_ENCRYPT_KEY`, per-node `API_KEY`); never reuse across hosts.
- Keep a random `URLPATH` prefix; serve behind TLS (self-signed minimum,
  Let's Encrypt preferred); leave `TRUSTED_PROXY=false` unless behind a
  proxy you control.
- `DOC=false` in production; back up `/opt/ovmanager/data` and
  `/etc/openvpn` regularly and test restores.
