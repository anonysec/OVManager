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

## Self-signed node TLS fallback (known risk)

The panel first verifies a node's TLS certificate strictly. If verification
fails — normal for a node using a self-signed certificate, which is the
installer default — it retries the request once with verification disabled.
A `node.tls_unverified` audit event is written the first time this happens
per node.

The risk: an active network attacker who can intercept the connection to the
node can impersonate it and capture the node's API key, which is sent with
every request. The fallback is deliberate, so self-signed nodes keep working.

Mitigations:

- Use a Let's Encrypt certificate on nodes so strict verification passes.
- Watch the node's TLS chip in the UI; "unverified (self-signed)" means
  requests to that node are not protected against impersonation.
- Check the audit log for `node.tls_unverified` events and investigate.

## Hardening checklist (production)

- Install with random secrets (`ADMIN_PASSWORD`, `BOT_ENCRYPT_KEY`,
  `NODE_ENCRYPT_KEY`, per-node `API_KEY`); never reuse across hosts.
- Keep a random `URLPATH` prefix; serve behind TLS (self-signed minimum,
  Let's Encrypt preferred); leave `TRUSTED_PROXY=false` unless behind a
  proxy you control.
- `DOC=false` in production; back up `/opt/ovmanager/data` and
  `/etc/openvpn` regularly and test restores.
