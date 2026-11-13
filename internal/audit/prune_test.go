// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package audit

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPruneFileDropsOldLinesAndKeepsMode(t *testing.T) {
	path := filepath.Join(t.TempDir(), "audit.jsonl")
	body := `{"id":1,"ts":10,"action":"old"}
{"id":2,"ts":100,"action":"new"}
not json
`
	if err := os.WriteFile(path, []byte(body), 0o640); err != nil {
		t.Fatal(err)
	}
	if removed := pruneFile(path, 50); removed != 1 {
		t.Fatalf("removed = %d, want 1", removed)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), `"old"`) {
		t.Fatalf("old line survived: %s", data)
	}
	if !strings.Contains(string(data), `"new"`) || !strings.Contains(string(data), "not json") {
		t.Fatalf("kept lines lost: %s", data)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o640 {
		t.Fatalf("mode = %o, want 640", info.Mode().Perm())
	}
}
