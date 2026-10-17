# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

.PHONY: setup build test lint verify clean

setup:
	go mod download
	cd frontend && npm ci

# One binary = the panel (bare invocation) + the `ovm` operator CLI.
build:
	go build -o ovmanager ./cmd/ovmanager

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
	cd frontend && npm run verify

clean:
	rm -f ovmanager
	rm -rf frontend/dist
