# OVManager

[![Version](https://img.shields.io/badge/version-2.1.3-blue)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-All%20Rights%20Reserved-red)](LICENSE)

Web panel for a self-hosted OpenVPN service: users, traffic quotas, expiry dates, device limits and live sessions across one or many servers.

**Highlights:** claim-key first login · single binary · SQLite · no compile on server · limits enforced on nodes · accounting that can't double-bill · self-updating with rollback.

## Install

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
```

Zero questions by default. Interactive mode: add `-i`. See [docs](https://anonysec.github.io/OVManager/).

## Day-to-day

```bash
ovmanager status | logs | update | backup
```

## License

Forks allowed. Redistribution and rebranding not. See [LICENSE](LICENSE).