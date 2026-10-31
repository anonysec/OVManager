// Parity tests for Phase 5: the cobra CLI must print byte-identical golden
// screens for status/doctor against a fixture DATA_DIR, and the update
// orchestrator must have a dry-run that touches nothing.
package tests

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/cli"
	"github.com/anonysec/OVManager/go/internal/db"
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
	oldTimer := cli.BackupTimerUnit
	t.Cleanup(func() {
		cli.FetchHealth, cli.ServiceState, cli.PrimaryIP = oldHealth, oldState, oldIP
		cli.SystemctlEnabled, cli.UnitPath, cli.DiskFreeMB = oldEnabled, oldUnit, oldDisk
		cli.LegacyBackupDir = oldLegacy
		cli.BackupTimerUnit = oldTimer
	})
	cli.LegacyBackupDir = filepath.Join(root, "var-backups")
	cli.BackupTimerUnit = func(install cli.Install) string { return filepath.Join(root, "no-backup.timer") }
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

// TestCLIStatus golden-compares `ovmanager status` against manager.sh's rows.
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

// TestCLIDoctor golden-compares `ovmanager doctor` against a fixture with two known
// failures (no backup yet, worker not started) and everything else passing.
func TestCLIDoctor(t *testing.T) {
	installDir, dataDir := cliFixture(t)
	var out bytes.Buffer
	code := cli.Run([]string{"doctor", "--install-dir", installDir, "--data-dir", dataDir}, &out)
	if code != 1 {
		t.Fatalf("exit = %d, want 1 (failing checks)\n%s", code, out.String())
	}
	want := strings.Join([]string{
		"  XX 1 problems",
		"",
		"   Backup         none yet",
		"   fix            ovmanager backup",
		"",
		"    11 other checks passed — detail: ovmanager doctor --all",
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

// TestCLIHealthHTTPS: ovmanager health reports healthy against an HTTPS-only local
// server (plain probe fails, HTTPS retry with InsecureSkipVerify succeeds).
func TestCLIHealthHTTPS(t *testing.T) {
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" {
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"status":"ok"}`))
			return
		}
		http.NotFound(w, r)
	}))
	defer srv.Close()
	u, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("PORT", u.Port())

	var out bytes.Buffer
	code := cli.Run([]string{"health"}, &out)
	if code != 0 {
		t.Fatalf("exit = %d, want 0\n%s", code, out.String())
	}
	if !strings.Contains(out.String(), "ok") {
		t.Errorf("output = %q, want ok", out.String())
	}
}

// TestCLIResetPasswordRevokesActualOwner: sessions of the owner row's actual
// username are revoked, not ADMIN_USERNAME from .env.
func TestCLIResetPasswordRevokesActualOwner(t *testing.T) {
	installDir, dataDir := cliFixture(t)

	conn, err := db.Open(filepath.Join(dataDir, "ovmanager.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := conn.Exec(testSchema); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO admins (username, password, is_owner) VALUES ('bob', 'oldhash', 1)`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO sessions (token_hash, username, role, created_at, expires_at, last_seen_at) VALUES ('h1','bob','owner',0,9999999999,0)`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO sessions (token_hash, username, role, created_at, expires_at, last_seen_at) VALUES ('h2','admin','owner',0,9999999999,0)`); err != nil {
		t.Fatal(err)
	}

	t.Setenv("OVM_ADMIN_PASS", "new-password-123")
	var out bytes.Buffer
	code := cli.Run([]string{"reset-password", "--install-dir", installDir, "--data-dir", dataDir}, &out)
	if code != 0 {
		t.Fatalf("exit = %d, want 0\n%s", code, out.String())
	}

	var bobCount, adminCount int
	if err := conn.QueryRow(`SELECT COUNT(*) FROM sessions WHERE username='bob'`).Scan(&bobCount); err != nil {
		t.Fatal(err)
	}
	if err := conn.QueryRow(`SELECT COUNT(*) FROM sessions WHERE username='admin'`).Scan(&adminCount); err != nil {
		t.Fatal(err)
	}
	if bobCount != 0 {
		t.Errorf("bob sessions not revoked: %d", bobCount)
	}
	if adminCount != 1 {
		t.Errorf("admin sessions unexpectedly changed: %d", adminCount)
	}
	if !strings.Contains(out.String(), "revoked 1 active session") {
		t.Errorf("output missing revocation line:\n%s", out.String())
	}
}

// The panel tells the operator "Run: ovmanager auth key" when it cannot read the
// setup key, and "ovmanager auth reset" when the key is lost. Those commands must
// exist, or the panel's own recovery instructions are a dead end.
func TestCLIAuthKeyCreatesAndKeepsTheKey(t *testing.T) {
	installDir, dataDir := cliFixture(t)
	keyPath := filepath.Join(dataDir, "owner-claim.key")

	var out bytes.Buffer
	code := cli.Run([]string{"auth", "key", "--install-dir", installDir, "--data-dir", dataDir}, &out)
	if code != 0 {
		t.Fatalf("ovmanager auth key: exit %d, output %s", code, out.String())
	}
	raw, err := os.ReadFile(keyPath)
	if err != nil {
		t.Fatalf("no key file: %v", err)
	}
	first := strings.TrimSpace(string(raw))
	if first == "" {
		t.Fatal("the key file is empty")
	}
	if !strings.Contains(out.String(), first) {
		t.Errorf("the key is not printed: %s", out.String())
	}

	// A rerun must not invalidate a key the panel is still holding.
	out.Reset()
	if code := cli.Run([]string{"auth", "key", "--install-dir", installDir, "--data-dir", dataDir}, &out); code != 0 {
		t.Fatalf("ovmanager auth key (rerun): exit %d", code)
	}
	raw, _ = os.ReadFile(keyPath)
	if got := strings.TrimSpace(string(raw)); got != first {
		t.Errorf("the key changed on a rerun: %q -> %q", first, got)
	}

	// A reset is the lost-key case: a fresh key, and the old one stops working.
	out.Reset()
	if code := cli.Run([]string{"auth", "reset", "--install-dir", installDir, "--data-dir", dataDir}, &out); code != 0 {
		t.Fatalf("ovmanager auth reset: exit %d", code)
	}
	raw, _ = os.ReadFile(keyPath)
	if got := strings.TrimSpace(string(raw)); got == first {
		t.Error("ovmanager auth reset kept the old key")
	}
}
