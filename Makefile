# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

.PHONY: setup build test lint verify clean

setup:
	go mod download
	cd web && npm ci

# One binary = the panel (bare invocation) + the `ovm` operator CLI. The SPA is
# embedded (internal/webfs/dist), so the build stages web/dist into the package
# before compiling. web/dist is built only when absent — CI hands it over as an
# artifact, so the Go job never needs npm.
build:
	@if [ ! -f web/dist/index.html ]; then \
		echo "web/dist missing — building SPA"; \
		cd web && npm ci && npm run build; \
	fi
	@mkdir -p internal/webfs/dist
	@cp -a web/dist/. internal/webfs/dist/
	@cp -a web/templates/subscription.js internal/webfs/templates/subscription.js
	go build -o ovmanager ./cmd

# The full Go suite. tests holds the cross-implementation parity tests, so
# this is the gate that used to be `pytest tests/ -n auto`.
test:
	go test ./...

# go vet only: `gofmt -l` still flags pre-existing files, so it is not a gate
# yet. Add `gofmt -l | tee /dev/stderr | grep -q . && exit 1` when the tree is
# clean.
lint:
	go vet ./cmd/... ./internal/...

verify: test
	cd web && npm run verify

clean:
	rm -f ovmanager
	rm -rf web/dist
	find internal/webfs/dist -mindepth 1 ! -name .gitkeep -delete
