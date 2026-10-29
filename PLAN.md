# OVManager improvement plan (audit)

> Progress: Phase 1 mostly done (README TLS section, installer `tls=` summary, glyph cleanup). Phase 2 done (tls help string, expanded root menu, /dev/tty consistency). Phase 3 partial (renamed tls_legacy→tls_migrate, export.go→password_policy.go, gitignored cover.out); `node`/`nodeclient` rename deferred. Phase 4 (squash releases) deferred.

## Phase 1 — Docs & text (low risk, high user impact)
- Update README TLS section and command table: `ovmanager tls` opens an interactive menu (not read-only); subcommands `issue`, `selfsigned`, `install`, `renew`, `remove`, `status`; installer flags `--ssl`, `--domain`, `--ip`, `--port`, `--path`, `--yes`, `--docker`, `--purge`, `--dest`.
- Standardize user-facing term to `tls` (installer summary `tls=…` instead of `ssl=…`; keep `ssl` only as a `tls` alias).
- Non-interactive summary prints `tls=none (run 'ovmanager tls' to enable)` when no SSL.
- Standardize log prefixes: keep `colorized_echo` levels only, drop mixed `✓/⚠/…/.` glyphs in installer output.
- Update CHANGELOG.md for 2.1.x.

## Phase 2 — CLI UX
- Make `ovmanager tls` help advertise subcommands (`Use: "tls [status|issue|selfsigned|install|remove|renew]"`) while still opening the menu on bare TTY invocation.
- Read input from `/dev/tty` in both root and TLS menus (consistency).
- Expand the root interactive menu to include backup/update/doctor/logs, or remove it and rely on `--help`. Decide per question below.
- Keep `--help` as the non-TTY default for `ovmanager` (no change).

## Phase 3 — Naming cleanup (refactor, higher churn)
- Rename `internal/node` → `internal/nodehub` and `internal/nodeclient` → `internal/nodeagent` (or merge) to disambiguate server-side node management from the agent client.
- Consolidate `internal/panel/tls_*.go` into `tls.go` + `tls_acme.go`; document or remove `tls_legacy.go`.
- Rename `internal/auth/export.go` to reflect its content; fold `internal/cli/util.go` helpers into their callers.
- Gitignore the `ovmanager` binary and `cover.out` build artifacts; remove tracked copies.
- Document the `test/` vs co-located `*_test.go` split in README/CONTRIBUTING.

## Phase 4 — Release hygiene
- Squash 2.1.3→2.1.8 into a single 2.2.0 release with one CHANGELOG entry; avoid point-release churn.

## Open questions
1. Root interactive menu scope: expand it (backup/update/doctor/logs) or drop it and rely solely on `--help`/subcommands?
2. `node`/`nodeclient` rename: worth the churn now, or defer? Any external importers (OVNode?) reference these package paths?
3. `tls_legacy.go`: still needed for migration from pre-2.0 installs, or deletable? Who is the oldest supported install?
4. Term `tls` vs `ssl`: drop the `ssl` alias entirely, or keep as alias for muscle memory? (Recommend keep alias, standardize text only.)
5. Installer `--ssl` flag values: keep `domain|ip|custom|selfsigned|none`, or rename `selfsigned` → `self-signed` for readability (breaks existing scripts)?
6. Should the installer auto-free port 80 (with confirmation) like the binary now does, instead of warning-and-skipping? Or keep installer conservative and let users run `ovmanager tls` post-install?
7. Gitignored build artifacts: is `ovmanager` (root binary) intentionally committed for `go:embed`/release convenience, or accidental?
8. CHANGELOG ownership: who updates it — release workflow or manual? Should the workflow fail if CHANGELOG lacks the version?
