# OVManager Architecture & Roadmap

**Status:** Updated for the 2.0.0 baseline release line.

## Architecture Baseline (2.0.0)

- **Systemd Service Architecture**: Runs natively as `ovmanager.service` via `ovmanager-server` binary on Linux hosts.
- **Single-Binary Assembly**: Go 1.27 embedding modernc SQLite and the React 19 SPA (`internal/webfs/dist`).
- **Hybrid Operator CLI**: `ovmanager` CLI provides direct subcommands with arguments (`ovmanager restart`, `ovmanager status`, `ovmanager logs -f`) and an interactive TUI menu when invoked bare on a terminal.
- **Standalone Installer**: Self-contained `install.sh` with inlined system helpers, cryptographic Ed25519 binary signature verification, and commit-pinned OVNode installation.
- **Cryptographic Security**:
  - Ed25519 signature verification on all binary releases and updates.
  - AES-256-GCM encryption of secrets at rest (`secret.key` at mode 0600).
  - Explicit confirmation and SHA-256 fingerprint verification on node TLS certificates (TOFU and re-pin).
  - Sanitized Telegram daily backups (active sessions, bot tokens, and node keys redacted).
  - AES-256-GCM encrypted offsite backups.
  - Hardened Content-Security-Policy with per-request cryptographic nonces.

## Test Suite Architecture

OVManager tests are divided into three complementary suites:

1. **Co-located Unit Tests (`internal/*_test.go` and `cmd/*_test.go`)**:
   - Fast, isolated unit tests co-located directly with the code under test.
   - Covers core internal logic: cryptography, session verification, client IP / trusted CIDRs, certificate fingerprints, rate limiting, and config parsing.
   - Run via `go test ./internal/... ./cmd/...`.

2. **Integration & API Parity Tests (`test/*.go`)**:
   - High-level full server integration tests verifying complete HTTP request/response lifecycles, database schema migrations, and route authentication gates across the entire assembled panel.
   - Run via `go test ./test/...`.

3. **Installer Regression Tests (`test/installer/test_install.py`)**:
   - Python unittest suite testing `install.sh` in isolation with mock environments.
   - Covers non-interactive flags, prompt handling, node installer execution, and cryptographic signature rejection of tampered binaries.
   - Run via `python3 -m unittest discover -s test/installer -v`.

4. **Frontend Verification (`web/`)**:
   - Full vitest suite (104+ tests), TypeScript compilation check (`tsc --noEmit`), token accessibility check (`check:tokens`), i18n completeness (`check:i18n`), and RTL stylesheet guards (`check:rtl`).
   - Run via `cd web && npm run verify`.
