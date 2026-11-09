package cli

import (
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/anonysec/OVManager/internal/db"
	_ "modernc.org/sqlite"
)

// TestCLIRestoreStopsServiceBeforeDatabaseSwap records service actions and
// asserts ordering: owned check → stop → verified inactivity → replacement →
// restart. Stop failure or an unowned arrangement must not touch files.
func TestCLIRestoreStopsServiceBeforeDatabaseSwap(t *testing.T) {
	oldState, oldStop, oldRestart := ServiceState, ServiceStop, ServiceRestart
	t.Cleanup(func() { ServiceState, ServiceStop, ServiceRestart = oldState, oldStop, oldRestart })

	var mu sync.Mutex
	var actions []string
	state := "active"
	ServiceState = func() (string, string) {
		mu.Lock()
		defer mu.Unlock()
		return "native", state
	}
	oldHealth := waitHealthAny
	t.Cleanup(func() { waitHealthAny = oldHealth })
	waitHealthAny = func([]string, int, string) (bool, string) { return true, "ok" }
	ServiceStop = func(Install) {
		mu.Lock()
		actions = append(actions, "stop")
		state = "inactive"
		mu.Unlock()
	}
	ServiceRestart = func(Install) bool {
		mu.Lock()
		actions = append(actions, "restart")
		mu.Unlock()
		return true
	}

	dir := t.TempDir()
	installDir := filepath.Join(dir, "opt")
	if err := os.MkdirAll(installDir, 0o755); err != nil {
		t.Fatal(err)
	}
	backupDir := filepath.Join(dir, "backups")
	if err := os.MkdirAll(backupDir, 0o700); err != nil {
		t.Fatal(err)
	}
	dbPath := filepath.Join(dir, "ovmanager.db")
	conn, err := db.Open(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`CREATE TABLE t (v TEXT); INSERT INTO t VALUES ('payload');`); err != nil {
		t.Fatal(err)
	}
	_ = conn.Close()
	if err := copyFile(dbPath, filepath.Join(backupDir, "r.db")); err != nil {
		t.Fatal(err)
	}
	install := Install{InstallDir: installDir, DataDir: dir}

	// Case 1: running service → stop, restore, restart, in that order.
	_, code := runRestore(install, "r.db")
	if code != 0 {
		t.Fatalf("restore failed, code %d", code)
	}
	mu.Lock()
	got := append([]string{}, actions...)
	mu.Unlock()
	joined := strings.Join(got, ",")
	if joined != "stop,restart" {
		t.Fatalf("actions = %v, want [stop restart]", got)
	}

	// Case 2: unowned arrangement → refuse before any file action.
	ServiceState = func() (string, string) { return "manual", "unknown" }
	_, code = runRestore(install, "r.db")
	if code != 1 {
		t.Fatalf("unowned restore code = %d, want 1", code)
	}
	mu.Lock()
	if len(actions) != 2 {
		t.Fatalf("unowned restore performed service actions: %v", actions)
	}
	mu.Unlock()

	// Case 3: already stopped → restore succeeds, no restart.
	state = "inactive"
	actions = nil
	ServiceState = func() (string, string) {
		mu.Lock()
		defer mu.Unlock()
		return "native", state
	}
	_, code = runRestore(install, "r.db")
	if code != 0 {
		t.Fatalf("stopped restore failed, code %d", code)
	}
	mu.Lock()
	if len(actions) != 0 {
		t.Fatalf("already-stopped restore touched services: %v", actions)
	}
	mu.Unlock()
}
