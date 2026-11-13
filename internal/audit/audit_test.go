// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package audit

import (
	"os"
	"path/filepath"
	"sync"
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

// When /var/log is unusable (the pre-unit installs), the trail must land in
// the data dir rather than vanish; the same rule makes every process agree.
func TestPathFallsBackToDataDir(t *testing.T) {
	root := t.TempDir()
	primary := filepath.Join(root, "audit-dir-is-a-file")
	if err := os.WriteFile(primary, []byte("not a dir"), 0o600); err != nil {
		t.Fatal(err)
	}
	prevDir := auditDir
	auditDir = primary
	pathOnce = sync.Once{}
	defaultPath = ""
	t.Cleanup(func() { auditDir = prevDir; pathOnce = sync.Once{}; defaultPath = "" })
	t.Setenv(PathEnv, "")
	t.Setenv("DataDir", filepath.Join(root, "data"))

	got := Path()
	want := filepath.Join(root, "data", "audit.jsonl")
	if got != want {
		t.Fatalf("Path = %q, want the data-dir fallback %q", got, want)
	}
	Record(nil, "admin", "Auth.Login", "info", "login", nil)
	if lines := ReadLines(); len(lines) == 0 {
		t.Fatal("fallback audit file was not written")
	}
}
