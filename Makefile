# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

.PHONY: setup build test lint verify clean version check-version

setup:
	go mod download
	cd web && npm ci

# Single version source: internal/version/version.go. Regenerates the SPA's
# build-time constant (web/src/version.ts), package.json, and README pins so
# the binary, the installer tag, the badge and the frontend never drift.
version:
	@v=$$(grep -m1 'var Version' internal/version/version.go | cut -d'"' -f2); \
	sed -i -E "s/^  \"version\": \".*\"/  \"version\": \"$$v\"/" web/package.json; \
	sed -i -E "s|badge/version-[0-9.]*-blue|badge/version-$$v-blue|" README.md; \
	sed -i -E "s|anonysec/OVManager/v[0-9.]+/install.sh|anonysec/OVManager/v$$v/install.sh|" README.md; \
	sed -i -E "s|\(v[0-9.]+, matching the binary's version constant\)|\(v$$v, matching the binary's version constant\)|" README.md; \
	echo "version -> $$v"

check-version:
	@v=$$(grep -m1 'var Version' internal/version/version.go | cut -d'"' -f2); \
	grep -q "badge/version-$$v-blue" README.md || { echo "README badge mismatch with version.go ($$v)"; exit 1; }; \
	grep -q "anonysec/OVManager/main/install.sh" README.md || { echo "README install pin (main) missing"; exit 1; }; \
	grep -q "(v$$v, matching the binary's version constant)" README.md || { echo "README prose version mismatch with version.go ($$v)"; exit 1; }; \
	echo "version parity OK: $$v"

# One binary = the panel (bare invocation) + the `ovmanager` operator CLI. The SPA is
# embedded (internal/webfs/dist), so the build stages web/dist into the package
# before compiling. web/dist is built only when absent — CI hands it over as an
# artifact, so the Go job never needs npm. Keep .gitkeep in the staged embed
# directory so go vet works from a source-only checkout and `make build` is safe.
build:
	@if [ ! -f web/dist/index.html ]; then \
		echo "web/dist missing — building SPA"; \
		$(MAKE) -s version; \
		cd web && npm ci && npm run build; \
	fi
	@mkdir -p internal/webfs/dist
	@find internal/webfs/dist -mindepth 1 ! -name .gitkeep -delete
	@cp -a web/dist/. internal/webfs/dist/
	@cp -a web/templates/subscription.js internal/webfs/templates/subscription.js
	go build -o ovmanager ./cmd

# The full Go suite. tests holds the cross-implementation parity tests, so
# this is the gate that used to be `pytest tests/ -n auto`.
test:
	go test ./...

# go vet across the module plus a gofmt gate: the tree is clean, so any
# unformatted file now fails lint instead of drifting.
lint:
	go vet ./...
	@test -z "$$(gofmt -l .)" || { gofmt -l .; exit 1; }

verify: test version check-version
	cd web && npm run verify

clean:
	rm -f ovmanager
	rm -rf web/dist
	find internal/webfs/dist -mindepth 1 ! -name .gitkeep -delete
