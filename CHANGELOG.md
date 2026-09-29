# Changelog

## 1.0.0 — 2026-09-29

First public release.

**Install**
- One installer, with the shared shell helpers sourced from a single library
  instead of being copied into it.
- Only three flags: `-y/--yes`, `--docker`, `-h/--help`. Everything else is an
  `OVM_*` setting, and the older flag spellings still work.
- The installer fetches a verified release archive; nothing is built from source.
- Self-signed TLS by default, with the browser warning named rather than hidden.

**First login**
- The installer mints no owner password. It prints a one-time claim key, and the
  owner account is created in the browser with a password you choose. The key is
  single-use, rate-limited, and the password is stored as a hash in the database —
  never in `.env`.

**Manage**
- `ovm status`, `ovm doctor [--fix]`, `ovm logs`, `ovm backup`, `ovm restore`,
  `ovm https`, `ovm update`, `ovm rollback`, `ovm reset-password`,
  `ovm completion`, `ovm version-script`.
- Updates are staged and verified, and roll back automatically if the new version
  does not come up.
- Uninstall keeps data unless `--purge`.
