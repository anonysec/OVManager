# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

.PHONY: setup test lint verify openapi clean

setup:
	uv sync --frozen
	cd frontend && npm ci

# -n auto runs the suite across cores. Safe because tests/conftest.py allocates
# its throwaway data dir with tempfile.mkdtemp() at import time, so each worker
# process gets its own database. Verified at 4, 8 and 16 workers as well as
# auto, to shake out shared state that two workers would hide.
#
# The default per-test distribution is deliberate: --dist loadfile pins each
# file to a single worker, and measured 90.9s against 29.9s for the same suite.
test:
	.venv/bin/python -m pytest tests/ -q -n auto

lint:
	.venv/bin/ruff check backend bot cli main.py tests scripts/bench
	.venv/bin/ruff format --check backend bot cli main.py tests scripts/bench
	bash -n install.sh manager.sh scripts/lib/*.sh
	git diff --check
	cd frontend && npx eslint src/

verify: lint
	cd frontend && npm run verify
	.venv/bin/python scripts/export_openapi.py

# Not a test: the figures depend on the machine's core count, so a fixed
# assertion would test the runner rather than the code. The properties these
# numbers justify are covered by tests/test_node_fanout_budget.py and
# tests/test_worker_process.py. See scripts/bench/README.md.
bench:
	.venv/bin/python scripts/bench/node_fanout.py
	.venv/bin/python scripts/bench/jobs_worker.py

openapi:
	.venv/bin/python scripts/export_openapi.py

clean:
	rm -rf frontend/dist backend/__pycache__ .pytest_cache
	find backend bot tests -name '__pycache__' -type d -prune -exec rm -rf {} +
