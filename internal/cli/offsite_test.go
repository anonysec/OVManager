package cli

import (
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/go/internal/db"
)

// A copy that cannot happen must not be silent: the outcome belongs in the
// audit log, so the operator can see that the offsite copy did not happen.
func TestRecordOffsiteCopyWritesTheOutcome(t *testing.T) {
	dir := t.TempDir()
	conn, err := db.Open(filepath.Join(dir, "ovmanager.db"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, actor TEXT, action TEXT, target TEXT, detail TEXT)`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, offsite_backup_target VARCHAR)`); err != nil {
		t.Fatal(err)
	}
	_ = conn.Close()

	recordOffsiteCopy(dir, "backup@server:/backups", "rsync", nil)

	conn2, err := db.Open(filepath.Join(dir, "ovmanager.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn2.Close() }()
	var action, detail string
	err = conn2.QueryRow(`SELECT action, detail FROM audit_logs ORDER BY id DESC LIMIT 1`).Scan(&action, &detail)
	if err != nil {
		t.Fatalf("no audit row: %v", err)
	}
	if action != "backup_offsite" {
		t.Errorf("action = %q, want backup_offsite", action)
	}
	if detail == "" {
		t.Error("the audit row carries no detail")
	}
}

// A target that is not usable must fail loudly instead of being ignored.
func TestOffsiteCopyRejectsAnUnusableTarget(t *testing.T) {
	if _, err := offsiteCopy("", "/tmp/x.db"); err == nil {
		t.Error("an empty target should be an error")
	}
	if _, err := offsiteCopy("server:/backups/../etc", "/tmp/x.db"); err == nil {
		t.Error("a target with '..' should be an error")
	}
}
