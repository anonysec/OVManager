package panel

import (
	"database/sql"
	"errors"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/db"
)

// A restore whose swapped database will not reopen must not leave the panel
// running on a closed pool: the swap is rolled back and the panel keeps
// serving.
func TestRestoreRollsBackWhenTheSwappedDatabaseWillNotReopen(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("DATA_DIR", dir)
	live := filepath.Join(dir, "ovmanager.db")
	conn, err := db.Open(live)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	svc := auth.NewService(conn, dir)
	h := &Handler{Svc: svc}

	// A candidate with the same schema version. The WAL is checkpointed
	// first: the copy takes the main file only.
	if _, err := conn.Exec(`PRAGMA wal_checkpoint(TRUNCATE)`); err != nil {
		t.Fatal(err)
	}
	candidate := filepath.Join(dir, "candidate.db")
	if err := copyFile(live, candidate); err != nil {
		t.Fatal(err)
	}

	// The reopen after the swap fails; the rollback's reopen succeeds.
	orig := openLive
	defer func() { openLive = orig }()
	calls := 0
	openLive = func(path string) (*sql.DB, error) {
		calls++
		if calls == 1 {
			return nil, errors.New("simulated: open failed")
		}
		return orig(path)
	}

	res := h.atomicDBRestore(candidate, "owner", "test")
	if res.Success {
		t.Fatalf("restore reported success: %s", res.Msg)
	}
	data, _ := res.Data.(map[string]any)
	if data["rolled_back"] != true {
		t.Fatalf("the swap was not rolled back: %v (%s)", data, res.Msg)
	}
	if err := svc.DB().Ping(); err != nil {
		t.Fatalf("the panel was left without a usable pool: %v", err)
	}
}
