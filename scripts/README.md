# scripts/ — the simulated installer repo

This directory is the installer as if it were its own repository
(PasarGuard keeps it as one): shell entry points stay at the repo root
because their paths are frozen contracts (`install.sh` is fetched by URL,
`manager.sh` is installed as `ovm`), but **everything else install-related
lives here**.

```
scripts/
├── README.md            # this file
├── lib/                 # one file per concern, sourced by manager.sh,
│                        # mirrored function-for-function inside install.sh
│   ├── common.sh        # colours, die, randomness (source first)
│   ├── prompt.sh        # ask/confirm/TUI picker/spinner, TTY guards
│   ├── env.sh           # atomic .env read/write
│   ├── system.sh        # systemd, firewall, health, panel URLs
│   ├── backup.sh        # safety backups + code snapshots (failover)
│   ├── tls.sh           # self-signed / acme.sh / Let's Encrypt
│   └── policy.sh        # password policy, release artifact URLs
├── compose/
│   └── docker-compose.yml   # dev-only panel compose (the installer
│                            # generates the real one per install)
├── export_openapi.py    # panel API tooling — NOT installer code
└── openapi.json         # generated (gitignored, `make openapi`)
```

Rules (all enforced by tests):

1. `install.sh` runs standalone via curl-pipe, so it carries full copies
   of every `lib/` function. `tests/test_lib_parity.py` fails on the
   first drifted byte.
2. Nothing under `lib/` may reference panel code (`backend|bot|frontend`
   Python imports) — pure shell + system tools only.
3. `export_openapi.py` is exempt from rules 1–2 (panel-side tooling).

If the installer ever becomes a real third repo, `git subtree split -P
scripts/` produces it with full history.
