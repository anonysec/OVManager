# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

.PHONY: setup test lint verify openapi clean

setup:
	uv sync --frozen
	cd frontend && npm ci

test:
	.venv/bin/python -m pytest tests/ -q

lint:
	.venv/bin/ruff check backend bot main.py tests
	bash -n install.sh manager.sh lib/common.sh
	git diff --check
	cd frontend && npx eslint src/
# NOTE: `ruff format` drifts on ~27 files (pre-existing, CI-ungated).
# Do not add it here until the tree is formatted in one dedicated commit.

verify: lint
	cd frontend && npm run verify
	.venv/bin/python scripts/export_openapi.py

openapi:
	.venv/bin/python scripts/export_openapi.py

clean:
	rm -rf frontend/dist backend/__pycache__ .pytest_cache
	find backend bot tests -name '__pycache__' -type d -prune -exec rm -rf {} +
