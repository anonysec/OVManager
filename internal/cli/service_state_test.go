package cli

import (
	"os"
	"path/filepath"
	"testing"
)

// TestServiceStateImpl parses systemctl output; is-active exits non-zero for
// inactive/failed, and those must still read as an owned native service.
func TestServiceStateImpl(t *testing.T) {
	dir := t.TempDir()
	script := `#!/bin/sh
case "$STATE" in
  active) echo active; exit 0;;
  inactive) echo inactive; exit 3;;
  failed) echo "failed"; exit 1;;
  missing) echo "could not be found"; exit 4;;
  *) echo "unknown"; exit 1;;
esac
`
	if err := os.WriteFile(filepath.Join(dir, "systemctl"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+":"+os.Getenv("PATH"))
	cases := []struct {
		state string
		mode  string
	}{
		{"active", "native"},
		{"inactive", "native"},
		{"failed", "native"},
		{"missing", "manual"},
	}
	for _, tc := range cases {
		t.Setenv("STATE", tc.state)
		mode, _ := serviceStateImpl()
		if mode != tc.mode {
			t.Fatalf("state %q: mode = %q, want %q", tc.state, mode, tc.mode)
		}
	}
}
