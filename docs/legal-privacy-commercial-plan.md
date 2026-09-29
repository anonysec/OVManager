# Legal, licensing, privacy, and commercial-use plan

> Planning document, not legal advice. Laws differ by operator, users, hosting location, and countries served. Project maintainers should have final public policies reviewed by qualified counsel before claiming legal compliance.

## Project commitment

OVManager and OVNode should remain genuinely free and open source for personal and commercial use.

Under the current MIT license, users may use, copy, modify, distribute, sublicense, and sell copies, subject to preserving the copyright and license notice. The project should state plainly:

- no license key is required;
- no seat, user, node, traffic, or revenue-based license fee is required;
- commercial use, hosting services, internal business use, modification, and resale are permitted by the project license;
- all core operational requirements work without a paid edition or proprietary license server;
- optional third-party infrastructure or services may charge their own fees;
- the software is provided without warranty under the MIT terms;
- the operator remains responsible for lawful VPN use, users, content, providers, and local compliance.

Do not say “copyright free,” “public domain,” or “no conditions.” MIT is permissive but still requires preservation of its notice.

## Recommended public license wording

Add a visible README section:

```text
Free for personal and commercial use

OVManager is licensed under the MIT License. You may use, modify,
distribute, host, and sell services built with it without paying a license
fee to this project. Keep the copyright and MIT license notice with copies
or substantial portions of the software.

There is no paid feature gate, node limit, user limit, or license server.
Third-party hosting, domains, certificate services, messaging services, and
other infrastructure may have their own terms or costs.
```

The exact `LICENSE` file should remain the canonical legal grant. Marketing copy must not add restrictions that conflict with it.

## License governance

### Repository files

Keep and maintain:

```text
LICENSE                    MIT license text
NOTICE                     Third-party notices that require attribution
THIRD_PARTY_LICENSES.md    Dependency name, version/source, license, notice link
PRIVACY.md                 Project/software privacy behavior
SECURITY.md                Vulnerability reporting and support policy
ACCEPTABLE_USE.md          Operator responsibilities and prohibited abuse guidance
TRADEMARKS.md              Name/logo policy, if maintainers want one
```

Source files may retain SPDX headers:

```text
SPDX-License-Identifier: MIT
```

Release archives, container images, and source distributions must include `LICENSE`, required notices, and a machine-readable SBOM.

### Dependency policy

“License free” cannot mean ignoring dependency licenses. Before every release:

- generate Python, JavaScript, container/base-image, and bundled-binary SBOMs;
- identify each dependency's exact license from authoritative package metadata/source;
- block unknown, missing, custom, source-available, non-commercial, evaluation, or incompatible licenses pending review;
- preserve attribution and notice obligations;
- track frontend assets, icons, fonts, country databases, copied shell snippets, and vendored code—not only package-manager dependencies;
- review optional tools installed or invoked by setup, including Docker/base images, OpenVPN, ACME clients, and system packages;
- record exceptions with maintainer and legal approval.

A permissive project license does not relicense third-party components. `docs/legal/THIRD_PARTY_LICENSES.md` and the SBOM explain their separate terms.

Add CI checks using an approved-license allowlist plus a deny/review list. Tool output assists review but is not a legal conclusion.

### Contributions

Choose and document one contribution model:

- contributions are accepted under the repository's MIT license; and
- contributors certify they have the right to submit them, preferably using Developer Certificate of Origin sign-off or an explicit pull-request attestation.

Do not introduce a contributor agreement that grants hidden relicensing rights without clear community review.

### Commercial policy

Paid support, hosting, consulting, or managed service may be offered without restricting the MIT software. Keep this distinction:

```text
Software license    Free under MIT
Support/service     May be offered separately
Infrastructure      Operator or third-party cost
```

Never make a required security update, backup restore, certificate renewal, node count, or disaster-recovery feature depend on a paid license check.

## Privacy model

### Roles

For a self-hosted installation:

- the server operator generally decides why/how panel and VPN-related personal data is processed and is typically the data controller or equivalent role;
- OVManager maintainers do not automatically receive installation data merely because the software is installed;
- external services configured by the operator—Telegram, SSH backup host, DNS, certificate authority, geolocation source, hosting provider—are separate recipients/processors under their own terms;
- project-hosted services, if introduced later, require a separate privacy notice and role analysis.

Avoid asserting a universal legal role; terminology varies by jurisdiction.

### Privacy-by-default commitments

- No telemetry, analytics, crash upload, update inventory, or “phone home” by default.
- Update checks contact the configured release host only when requested or explicitly enabled.
- Diagnostics and support bundles stay local unless the operator deliberately exports them.
- Support reports redact passwords, URL paths, session tokens, bot tokens, API credentials, backup keys, private keys, and unnecessary IP/user details.
- Telegram backup is opt-in and encrypted before upload.
- Offsite SSH backup is opt-in.
- Geolocation and other external lookups are documented and can be disabled where practical.
- Logs and audit data have bounded retention and operator controls.
- Security-essential audit events cannot be silently disabled without warning.

### Data inventory

Create a maintained table in `docs/legal/PRIVACY.md`:

| Data | Purpose | Default location | Default retention | External transfer |
|---|---|---|---|---|
| Admin account/session | Authentication and audit | Panel server | Session/config policy | None by default |
| User identity/labels | VPN administration | Panel server | Until deletion/retention policy | Nodes as required |
| IP addresses | Security, connection, node health | Panel/server logs | Bounded | Nodes; optional services |
| Traffic/usage | Quotas and reporting | Panel server | Configurable | None by default |
| Node credentials | Authenticated node management | Panel server + node | Until rotation/removal | Target node |
| Telegram identifiers/token | Bot/backup delivery | Panel server | Until disconnected | Telegram |
| Backup data | Recovery | Local/selected remote | Configurable | SSH/Telegram when enabled |
| Certificates/private keys | HTTPS/VPN operation | Managed private paths | Until replacement | CA for issuance; private keys never sent |
| Audit logs | Security/accountability | Panel server | Configurable | Export only |

The implemented product must be compared against this inventory in release review.

### Operator controls

Provide documented controls to:

- view configured external services and what data they receive;
- set log, audit, traffic-history, backup, and notification retention;
- export a user's stored data in a practical format;
- delete or anonymize a user where legally and operationally permitted;
- revoke sessions, credentials, subscription links, and certificates;
- disable Telegram/offsite integrations and remove stored tokens;
- erase an installation with explicit destructive confirmation;
- document data that must remain temporarily in security logs or backups and when it expires.

Deletion from the live database does not instantly erase retained backups. The privacy documentation must explain backup retention and deletion-on-expiry rather than promise immediate erasure everywhere.

## Multi-node privacy and security

OVManager controls OVNode servers in potentially different countries/providers. The operator must understand that:

- user configuration and operational identifiers may be transferred from panel to nodes;
- node health, IP, traffic, and connection information may return to the panel;
- cross-border transfer and provider rules may apply;
- each node needs documented location, provider, retention, and subprocessor assessment;
- node removal must revoke credentials and define what remains on the remote server;
- the panel should minimize fan-out payloads and never send unrelated user data to every node.

The product should provide a node data-flow screen or documentation showing what synchronizes and why.

## Telegram legal/privacy requirements

Before enabling Telegram features, show:

- which data will be sent;
- destination chat identity;
- that Telegram is an independent external service with its own terms/privacy policy;
- that encrypted backups still expose delivery metadata such as bot/chat, time, and file size;
- that notifications may contain operational information and should avoid sensitive user details;
- that service availability, retention, deletion, and jurisdiction are not controlled by OVManager.

Require explicit opt-in. A user enabling ordinary bot notifications has not automatically consented to backup transfer; configure those separately.

## HTTPS certificates for domain or IP

Document both supported address types legally and accurately:

- domain certificates require control of the domain and successful validation;
- public IP certificates require control/validation, an eligible public IP, and support from the selected certificate authority/client;
- certificate authorities are third parties with their own subscriber agreements and privacy policies;
- issuance may disclose domain/IP and contact/technical metadata to the authority and public certificate-transparency systems where applicable;
- temporary locally generated certificates avoid CA transfer but produce browser warnings;
- private keys remain local and are never sent to the certificate authority.

Do not guarantee that every IP, network, domain, or jurisdiction can receive an automatic certificate.

## Acceptable use and operator responsibility

Expand the existing acceptable-use statement into `docs/legal/ACCEPTABLE_USE.md` without imposing a new software-license restriction unless maintainers intentionally change licensing with legal review.

Clarify:

- the operator, not the project, runs the VPN service;
- the operator handles abuse reports, user authorization, provider terms, traffic retention, lawful requests, sanctions/export rules, and local VPN/telecommunications obligations;
- spam, scanning, malware, credential abuse, copyright infringement, and unlawful traffic should be prohibited by operator policy;
- quotas, expiry, logs, and account disabling are tools, not guarantees of legal compliance;
- operators should publish their own end-user terms and privacy notice.

Keep acceptable-use guidance separate from MIT license conditions. Adding field-of-use restrictions would make the project no longer standard MIT/open source.

## Security and cryptography notices

The project uses cryptography for HTTPS, credentials, encrypted backups, and VPN management. Release documentation should state:

- cryptography/export/import rules may vary by country;
- the operator is responsible for deployment jurisdiction;
- no claim of regulatory certification is made unless independently obtained;
- vulnerability reporting follows `SECURITY.md`;
- supported versions and security-update policy are explicit;
- default settings are security-oriented but do not guarantee compliance with GDPR, ePrivacy, CCPA/CPRA, HIPAA, PCI DSS, telecom rules, or other frameworks.

Avoid compliance badges or phrases such as “fully GDPR compliant” without a scoped legal and technical assessment.

## Trademark and project identity

MIT covers code, not necessarily project names or logos. Decide and document whether modified/commercial distributions may use OVManager/OVNode names and logos.

A balanced policy can allow truthful statements such as “based on OVManager” while preventing claims of official endorsement. Do not use trademark rules to restrict lawful use of the MIT code itself.

Review the OpenVPN name/logo usage and describe compatibility accurately. Do not imply endorsement by the OpenVPN project or company.

## Documentation structure

Restructure documentation into task-based navigation:

```text
README.md                         Overview, install, freedom/commercial-use summary
LICENSE                           Canonical MIT grant
NOTICE                            Required notices
THIRD_PARTY_LICENSES.md           Dependency notices
PRIVACY.md                        Data map and privacy behavior
ACCEPTABLE_USE.md                 Operator responsibilities
SECURITY.md                       Reporting and supported versions
TRADEMARKS.md                     Naming/logo policy

docs/
├── getting-started/
│   ├── install.md
│   ├── first-login.md
│   └── add-first-node.md
├── operations/
│   ├── status-service-autostart.md
│   ├── doctor-repair.md
│   ├── logs-support-report.md
│   ├── backups-remote-copies.md
│   ├── restore.md
│   ├── https-domain-or-ip.md
│   ├── update-failover.md
│   └── uninstall.md
├── nodes/
│   ├── multi-node.md
│   ├── security-data-flow.md
│   ├── update-nodes.md
│   └── replace-recover-node.md
├── recovery/
│   ├── lost-password-or-url.md
│   ├── interrupted-operation.md
│   ├── disaster-recovery.md
│   └── move-to-new-server.md
├── reference/
│   ├── ovm-cli.md
│   ├── ovn-cli.md
│   ├── configuration.md
│   ├── errors-exit-codes.md
│   ├── backup-format.md
│   └── compatibility.md
└── legal/
    ├── commercial-use.md
    ├── privacy-for-operators.md
    ├── third-party-services.md
    └── compliance-checklist.md
```

Rules:

- one canonical page per fact; other pages link instead of copying commands;
- generated CLI `--help` examples are tested against docs;
- beginner pages use `Install`, not implementation terminology;
- direct and Docker differences appear only where operationally relevant;
- every destructive procedure states backup, impact, rollback, and verification;
- every external service page links to its own terms/privacy page without claiming endorsement;
- versioned docs identify supported OVManager/OVNode combinations.

## Legal release gate

Before each release:

1. Generate SBOMs and third-party notice report.
2. Run dependency-license allowlist/review checks.
3. Run vulnerability scans and resolve/review findings.
4. Verify release archive/image contains license and notices.
5. Compare actual network destinations and stored data against `docs/legal/PRIVACY.md`.
6. Verify opt-in for Telegram, remote backup, and external lookups.
7. Test export, deletion, retention, and uninstall behavior.
8. Review new dependencies/assets/code provenance.
9. Review public claims for unsupported legal/security guarantees.
10. Record maintainer sign-off and items requiring counsel.

## Delivery plan

1. Publish commercial-use clarification, privacy model, acceptable-use guidance, and trademark decision.
2. Inventory all dependencies, assets, external calls, stored fields, logs, and transfer paths.
3. Generate SBOM and third-party notices in CI and release artifacts.
4. Implement privacy controls and external-service consent screens missing from the inventory.
5. Restructure docs without breaking old links; add redirects/link stubs.
6. Add a release legal/privacy checklist and assigned maintainers.
7. Obtain jurisdiction-appropriate legal review before making compliance claims or offering a managed commercial service.

## Acceptance criteria

- Personal and commercial use requires no project license fee or license server.
- README accurately summarizes MIT rights and conditions without overriding `LICENSE`.
- Every shipped dependency and asset has identified provenance/license or blocks release.
- Release artifacts include license, required notices, and SBOM.
- No telemetry or support upload occurs without explicit opt-in.
- Privacy documentation matches actual data, retention, and network behavior.
- Telegram backup and notifications have separate informed opt-ins.
- Domain/IP certificate flows disclose relevant third-party processing.
- Multi-node data flows and cross-server transfers are documented.
- Operators have practical export, retention, revocation, and deletion controls.
- Public materials avoid guarantees of universal legal or regulatory compliance.
