# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

.PHONY: setup test check check-cli check-bash lint verify openapi clean

setup:
	uv sync --frozen
	cd frontend && npm ci

# The full suite. 108s serial, ~71s here because this box has 2 cores and
# -n auto means 2 workers — distribution tuning cannot beat that, only cheaper
# tests can. Run this before a commit, not on every save.
#
# -n auto is safe because tests/conftest.py allocates its throwaway data dir
# with tempfile.mkdtemp() at import time, so each worker gets its own database.
# --dist loadfile pins each file to one worker, which keeps a file's own module
# state (and its pty fixtures) together.
#
# Known flake: two tests in test_installer_sh.py hardcode port 20950. Run
# concurrently, the loser fails with "Port 20950 is already in use" inside a
# test about password validation, so the message blames the wrong thing. It is
# not fixed yet — see the plan — and it fires on maybe one run in three.
test:
	.venv/bin/python -m pytest tests/ -q -n auto

# The inner loop. 14s against 108s, and it covers everything the CLI and the
# two installers actually print or dispatch — which is nearly every change to
# manager.sh, install.sh or scripts/lib/.
check: check-cli check-bash

check-cli:
	.venv/bin/python -m pytest -q -p no:cacheprovider \
	  tests/test_cli_shape.py tests/test_cli_render.py tests/test_env_ownership.py \
	  tests/test_cli.py tests/test_cli_ops.py tests/test_cli_accounts.py \
	  tests/test_cli_backup.py

check-bash:
	.venv/bin/python -m pytest -q -p no:cacheprovider \
	  tests/test_ui_output.py tests/test_lib_sourcing.py

# Split so each CI job can run the half it owns. The frontend half needs
# node_modules, which the backend job has no reason to install — pointing it at
# the combined target made it fail on a missing @eslint/js rather than on
# anything about the backend.
lint-backend:
	.venv/bin/ruff check backend cli main.py tests
	.venv/bin/ruff format --check backend cli main.py tests
	bash -n install.sh manager.sh scripts/lib/*.sh
	git diff --check

lint-frontend:
	cd frontend && npx eslint src/

lint: lint-backend lint-frontend

verify: lint
	cd frontend && npm run verify
	.venv/bin/python scripts/export_openapi.py

openapi:
	.venv/bin/python scripts/export_openapi.py

clean:
	rm -rf frontend/dist backend/__pycache__ .pytest_cache
	find backend tests -name '__pycache__' -type d -prune -exec rm -rf {} +
