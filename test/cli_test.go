// Parity tests for Phase 5: the cobra CLI must print byte-identical golden
// screens for status/doctor against a fixture DATA_DIR, and the update
// orchestrator must have a dry-run that touches nothing.
package tests

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/cli"
)

// cliFixture builds an install layout the CLI can read: an .env, a 0700 data
// dir, and a systemd unit naming the panel account. Every probe the golden
// screens depend on is injected, so the output is deterministic.
func cliFixture(t *testing.T) (installDir, dataDir string) {
	t.Helper()
	root := t.TempDir()
	installDir = filepath.Join(root, "opt", "ovmanager")
	dataDir = filepath.Join(root, "data")
	if err := os.MkdirAll(installDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(dataDir, 0o700); err != nil {
		t.Fatal(err)
	}
	env := "PORT=2095\nDATA_DIR=" + dataDir + "\nADMIN_USERNAME=admin\n"
	path := filepath.Join(installDir, ".env")
	if err := os.WriteFile(path, []byte(env), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}

	// A deterministic locale (ASCII glyphs) so the golden text is stable.
	for _, key := range []string{"LANG", "LC_ALL", "LC_CTYPE"} {
		t.Setenv(key, "")
	}

	// Inject every probe the two screens consult.
	oldHealth, oldState, oldIP := cli.FetchHealth, cli.ServiceState, cli.PrimaryIP
	oldEnabled, oldUnit, oldDisk := cli.SystemctlEnabled, cli.UnitPath, cli.DiskFreeMB
	oldLegacy := cli.LegacyBackupDir
	t.Cleanup(func() {
		cli.FetchHealth, cli.ServiceState, cli.PrimaryIP = oldHealth, oldState, oldIP
		cli.SystemctlEnabled, cli.UnitPath, cli.DiskFreeMB = oldEnabled, oldUnit, oldDisk
		cli.LegacyBackupDir = oldLegacy
	})
	cli.LegacyBackupDir = filepath.Join(root, "var-backups")
	cli.FetchHealth = func(url string, timeout time.Duration, cafile string) (bool, string) {
		return true, "1.6.0"
	}
	cli.ServiceState = func(composeFile string) (string, string) { return "native", "running" }
	cli.PrimaryIP = func() string { return "203.0.113.9" }
	cli.SystemctlEnabled = func(unit string) bool { return true }
	unit := filepath.Join(root, "ovmanager.service")
	if err := os.WriteFile(unit, []byte("[Service]\nUser=ovmanager\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	cli.UnitPath = func() string { return unit }
	cli.DiskFreeMB = func(path string) (int64, bool) { return 5000, true }
	return installDir, dataDir
}

// TestCLIStatus golden-compares `ovm status` against manager.sh's rows.
func TestCLIStatus(t *testing.T) {
	installDir, dataDir := cliFixture(t)
	var out bytes.Buffer
	code := cli.Run([]string{"status", "--install-dir", installDir, "--data-dir", dataDir}, &out)
	if code != 0 {
		t.Fatalf("exit = %d, want 0\n%s", code, out.String())
	}
	want := strings.Join([]string{
		"   Service        running",
		"   Health         ok",
		"   Version        v1.6.0",
		"   Open           http://203.0.113.9:2095/",
		"",
	}, "\n")
	if out.String() != want {
		t.Errorf("status output:\n got %q\nwant %q", out.String(), want)
	}
}

// TestCLIDoctor golden-compares `ovm doctor` against a fixture with two known
// failures (no backup yet, worker not started) and everything else passing.
func TestCLIDoctor(t *testing.T) {
	installDir, dataDir := cliFixture(t)
	var out bytes.Buffer
	code := cli.Run([]string{"doctor", "--install-dir", installDir, "--data-dir", dataDir}, &out)
	if code != 1 {
		t.Fatalf("exit = %d, want 1 (failing checks)\n%s", code, out.String())
	}
	want := strings.Join([]string{
		"  XX 2 problems",
		"",
		"   Backup         none yet",
		"   fix            ovm backup",
		"   Worker         not started (no lock file)",
		"   fix            ovm restart",
		"",
		"    11 other checks passed — detail: ovm doctor --all",
		"",
	}, "\n")
	if out.String() != want {
		t.Errorf("doctor output:\n got %q\nwant %q", out.String(), want)
	}
}

// TestCLIUpdateDryRun asserts the update orchestrator has a side-effect-free
// plan path: it prints the stages and does not touch the install or the data
// dir.
func TestCLIUpdateDryRun(t *testing.T) {
	installDir, dataDir := cliFixture(t)
	oldRootEuid := cli.UpdateRootEuid
	cli.UpdateRootEuid = func() int { return 0 }
	t.Cleanup(func() { cli.UpdateRootEuid = oldRootEuid })
	before, _ := os.Stat(filepath.Join(installDir, ".env"))
	var out bytes.Buffer
	code := cli.Run([]string{"update", "--dry-run", "--install-dir", installDir, "--data-dir", dataDir}, &out)
	if code != 0 {
		t.Fatalf("exit = %d, want 0\n%s", code, out.String())
	}
	if !strings.Contains(out.String(), "backup") || !strings.Contains(out.String(), "verify") {
		t.Errorf("dry-run plan missing stages:\n%s", out.String())
	}
	after, _ := os.Stat(filepath.Join(installDir, ".env"))
	if before == nil || after == nil || !before.ModTime().Equal(after.ModTime()) {
		t.Errorf("dry-run modified the install dir")
	}
}
