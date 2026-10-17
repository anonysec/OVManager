// Parity tests for the update data-dir fix: an in-tree DATA_DIR
// (install.sh --from-source lays it at <install>/data) must survive the
// stage→activate tree swap, while a release layout that keeps DATA_DIR outside
// the tree (/var/lib/ovmanager) is left untouched.
package tests

import (
	"os"
	"path/filepath"
	"testing"

	"ovmanager-go/internal/cli"
)

func mustWrite(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatalf("mkdir %s: %v", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
}

func mustRead(t *testing.T, path string) string {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	return string(raw)
}

func mustNotExist(t *testing.T, path string) {
	t.Helper()
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("%s should not exist (err=%v)", path, err)
	}
}

// TestUpdateMigratesInTreeDataDir: the previous tree's data dir is carried into
// the freshly extracted tree, and the previous tree keeps its copy (failover).
func TestUpdateMigratesInTreeDataDir(t *testing.T) {
	root := t.TempDir()
	prev := filepath.Join(root, ".ovmanager.previous")
	newDir := filepath.Join(root, "ovmanager") // freshly extracted: empty data/
	if err := os.MkdirAll(filepath.Join(newDir, "data"), 0o700); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, filepath.Join(prev, "data", "owner-claim.key"), "claim\n")
	mustWrite(t, filepath.Join(prev, "data", "ovmanager.db"), "db-bytes")

	decision, err := cli.MigrateDataIfInTree(prev, newDir)
	if err != nil {
		t.Fatalf("MigrateDataIfInTree: %v", err)
	}
	if got := mustRead(t, filepath.Join(newDir, "data", "owner-claim.key")); got != "claim\n" {
		t.Errorf("claim key not carried: %q (decision %q)", got, decision)
	}
	if got := mustRead(t, filepath.Join(newDir, "data", "ovmanager.db")); got != "db-bytes" {
		t.Errorf("db not carried: %q", got)
	}
	// prevDir/data untouched for failover.
	if got := mustRead(t, filepath.Join(prev, "data", "owner-claim.key")); got != "claim\n" {
		t.Errorf("previous data dir was mutated: %q", got)
	}
}

// TestUpdateSkipsMigrationWhenNewDataNonEmpty: a candidate that already ships
// data of its own must not be clobbered.
func TestUpdateSkipsMigrationWhenNewDataNonEmpty(t *testing.T) {
	root := t.TempDir()
	prev := filepath.Join(root, ".ovmanager.previous")
	newDir := filepath.Join(root, "ovmanager")
	mustWrite(t, filepath.Join(prev, "data", "left-over.txt"), "old")
	mustWrite(t, filepath.Join(newDir, "data", "downloaded.txt"), "new")

	decision, err := cli.MigrateDataIfInTree(prev, newDir)
	if err != nil {
		t.Fatalf("MigrateDataIfInTree: %v", err)
	}
	if got := mustRead(t, filepath.Join(newDir, "data", "downloaded.txt")); got != "new" {
		t.Errorf("new data clobbered: %q", got)
	}
	mustNotExist(t, filepath.Join(newDir, "data", "left-over.txt"))
	_ = decision
}

// TestUpdateSkipsMigrationWhenDataDirOutsideTree: release layout keeps DATA_DIR
// outside the install tree, so nothing is classified in-tree and no data dir is
// fabricated in the new tree.
func TestUpdateSkipsMigrationWhenDataDirOutsideTree(t *testing.T) {
	inst := cli.Install{
		InstallDir: "/opt/ovmanager",
		DataDir:    "/var/lib/ovmanager",
		Env:        map[string]string{"DATA_DIR": "/var/lib/ovmanager"},
	}
	if dir, inTree := cli.CaptureDataDir(inst); inTree {
		t.Fatalf("CaptureDataDir(%q) reported in-tree, want outside", dir)
	}

	root := t.TempDir()
	prev := filepath.Join(root, ".ovmanager.previous")
	newDir := filepath.Join(root, "ovmanager")
	mustWrite(t, filepath.Join(prev, "ovmanager"), "binary") // tree, no data/ subdir
	if err := os.MkdirAll(newDir, 0o755); err != nil {
		t.Fatal(err)
	}

	if _, err := cli.MigrateDataIfInTree(prev, newDir); err != nil {
		t.Fatalf("MigrateDataIfInTree: %v", err)
	}
	mustNotExist(t, filepath.Join(newDir, "data"))
}

// TestUpdateCaptureDataDirInTree: a from-source .env DATA_DIR=<install>/data is
// classified in-tree.
func TestUpdateCaptureDataDirInTree(t *testing.T) {
	inst := cli.Install{
		InstallDir: "/opt/ovmanager",
		DataDir:    "/opt/ovmanager/data",
		Env:        map[string]string{"DATA_DIR": "/opt/ovmanager/data"},
	}
	dir, inTree := cli.CaptureDataDir(inst)
	if !inTree {
		t.Fatalf("CaptureDataDir(%q) reported outside, want in-tree", dir)
	}
	if dir != "/opt/ovmanager/data" {
		t.Errorf("dir = %q, want /opt/ovmanager/data", dir)
	}
}
