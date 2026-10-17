# Local Installer OVM Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New `install-local.sh` (repo root) for fast dev loop; `install.sh`/`manager.sh` frozen (zero edits).

**Architecture:** Standalone minimal script (~150 lines): validate src → rsync to /opt/ovmanager → minimal .env + unit → uv sync → restart + localhost health check. Rerun = update. No docker/acme/backups/rollback. Unit content copied minimal from install.sh:1967+ heredoc, marked dev-only.

**Tech Stack:** bash (set -euo pipefail, quoted expansions), rsync, systemctl, uv.

**Spec:** exp-6 net map (tarball-only payload, hardcoded VERSION, local health endpoints). Gate 0 = minimal dev loop approved.

## Global Constraints

- Do NOT edit install.sh, manager.sh, or their helper blocks (byte-identity test).
- New file is exempt from install.sh net-scope tests (they target install.sh only) but keep it clean anyway: no curl|sh, no github URLs.
- Root-only actions guarded; `--help` works as non-root.
- Frontend/dist required — die with `cd frontend && npm run build` hint (matches install.sh:1807-1809).

## Review Focus

- rsync excludes .git/.venv/__pycache__/node_modules/.pytest_cache/.slim but keeps .env if present in dest (never overwrite existing .env).
- Unit ExecStart points at dest .venv + main.py with DATA_DIR/PORT env; daemon-reload before restart.
- Non-root run of install path dies before any write; --help exits 0.
- Args: --src (default: script's dir), --dest (default /opt/ovmanager), --uninstall, --help; unknown flag dies non-zero.
- Destructive rsync --delete scoped to dest dir only (assert dest path non-empty and != /).

---

### Task 1: install-local.sh

**Files:**
- Create: `/root/workspace/OVManager/install-local.sh`
- Test: `tests/test_local_install_sh.py`

**Interfaces:**
- Consumes: repo tree at --src, system uv/python3/rsync/systemctl
- Produces: running panel from dest + health OK

- [ ] **Step 1: Write failing test** — bash -n passes; --help exits 0 as non-root; unknown flag exits non-zero; missing frontend/dist in fake src dies with build hint (stub src dir, no root needed).
- [ ] **Step 2: Run, expect FAIL** (`pytest tests/test_local_install_sh.py -q -p no:cacheprovider` — file missing).
- [ ] **Step 3: Implement script** per architecture; unit minimal (Description, After=network.target, ExecStart=$dest/.venv/bin/python main.py, WorkingDirectory, Restart=on-failure, WantedBy); env file only if absent (ADMIN_USERNAME/ADMIN_PASSWORD placeholder + PORT 2095); restart + curl localhost /health (fail open with warning if panel slow).
- [ ] **Step 4: Verify PASS** — task test + `bash -n install-local.sh` + ruff-free (shell only).
- [ ] **Step 5: Commit** — `git add install-local.sh tests/test_local_install_sh.py && git commit -m "feat: local dev installer (mains frozen)"`.
