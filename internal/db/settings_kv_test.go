// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package db

import (
	"path/filepath"
	"strings"
	"testing"
)

// TestSettingsRegistryValidation: WriteSetting rejects unknown keys and
// round-trips registered ones.
func TestSettingsRegistryValidation(t *testing.T) {
	conn, err := OpenConfig(Config{Path: filepath.Join(t.TempDir(), "kv.db")})
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := Migrate(conn); err != nil {
		t.Fatal(err)
	}
	if err := WriteSetting(conn, KeyBackupLastSuccessDay, "2026-11-07", 1); err != nil {
		t.Fatalf("write registered: %v", err)
	}
	if got := ReadSetting(conn, KeyBackupLastSuccessDay); got != "2026-11-07" {
		t.Fatalf("read registered = %q, want 2026-11-07", got)
	}
	if err := WriteSetting(conn, SettingsKey("unregistered.key"), "x", 1); err == nil {
		t.Fatal("unregistered key write accepted")
	} else if !strings.Contains(err.Error(), "unknown settings_kv key") {
		t.Fatalf("wrong error: %v", err)
	}
}
