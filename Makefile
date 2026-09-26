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
	.venv/bin/ruff format --check backend bot main.py tests
	bash -n install.sh manager.sh scripts/lib/*.sh
	git diff --check
	cd frontend && npx eslint src/

verify: lint
	cd frontend && npm run verify
	.venv/bin/python scripts/export_openapi.py

openapi:
	.venv/bin/python scripts/export_openapi.py

clean:
	rm -rf frontend/dist backend/__pycache__ .pytest_cache
	find backend bot tests -name '__pycache__' -type d -prune -exec rm -rf {} +
