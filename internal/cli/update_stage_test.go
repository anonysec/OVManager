// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package cli

import (
	"os"
	"path/filepath"
	"testing"
)

// The systemd unit runs serverBin directly. install.sh installs the release
// under that name and points appSlug at it, so the updater must stage the
// same layout: staging only appSlug left ExecStart dangling and the service
// died with 203/EXEC during the 2.0.0 update.
func TestStagedTreeRunsServerBin(t *testing.T) {
	stage := t.TempDir()
	if err := os.WriteFile(filepath.Join(stage, serverBin), []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := linkServerEntrypoint(stage); err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(filepath.Join(stage, appSlug))
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("%s is not a symlink", appSlug)
	}
	target, err := os.Readlink(filepath.Join(stage, appSlug))
	if err != nil || target != serverBin {
		t.Fatalf("symlink target = %q, err %v", target, err)
	}
	if _, err := os.Stat(filepath.Join(stage, appSlug)); err != nil {
		t.Fatalf("symlink does not resolve: %v", err)
	}
}

func TestStagedTreeRequiresExecutableServerBin(t *testing.T) {
	stage := t.TempDir()
	if err := linkServerEntrypoint(stage); err == nil {
		t.Fatal("a stage without the binary must error")
	}
	if err := os.WriteFile(filepath.Join(stage, serverBin), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := linkServerEntrypoint(stage); err == nil {
		t.Fatal("a non-executable binary must error")
	}
}
