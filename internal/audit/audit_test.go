// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package audit

import (
	"os"
	"path/filepath"
	"testing"
)

// The audit trail must create its directory (the Logs page reads it) and
// survive being pointed at a nested path.
func TestRecordCreatesDirectoriesAndAppends(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "deeper", "audit.jsonl")
	t.Setenv(PathEnv, path)

	Record(nil, "admin", "User.Create", "info", "created user", map[string]any{"target": "amy"})
	Record(nil, "", "Auth.Login", "info", "login", nil)

	lines := ReadLines()
	if len(lines) != 2 {
		t.Fatalf("ReadLines returned %d entries, want 2", len(lines))
	}
	first := lines[0]
	if first["actor"] != "admin" || first["action"] != "User.Create" {
		t.Fatalf("first entry = %v", first)
	}
	if first["target"] != "amy" {
		t.Fatalf("target not promoted: %v", first)
	}
	if lines[1]["actor"] != "system" {
		t.Fatalf("empty actor = %v, want system", lines[1]["actor"])
	}
	if info, err := os.Stat(filepath.Dir(path)); err != nil || !info.IsDir() {
		t.Fatalf("audit directory not created: %v", err)
	}
}
