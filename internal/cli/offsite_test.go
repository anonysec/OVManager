package cli

import (
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/audit"
	"github.com/anonysec/OVManager/internal/db"
)

// A copy that cannot happen must not be silent: the outcome belongs in the
// audit log, so the operator can see that the offsite copy did not happen.
func TestRecordOffsiteCopyWritesTheOutcome(t *testing.T) {
	dir := t.TempDir()
	t.Setenv(audit.PathEnv, filepath.Join(dir, "audit.jsonl"))
	recordOffsiteCopy(dir, "backup@server:/backups", "rsync", nil)

	found := false
	for _, obj := range audit.ReadLines() {
		if obj["action"] == "backup_offsite" {
			found = true
			break
		}
	}
	if !found {
		t.Fatal("no audit row")
	}
	_ = db.Open
}
