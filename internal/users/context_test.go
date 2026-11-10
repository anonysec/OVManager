package users

import (
	"context"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/db"
)

func TestCancelledContextAbortsQuery(t *testing.T) {
	conn, err := db.Open(filepath.Join(t.TempDir(), "ctx.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := conn.QueryContext(ctx, `SELECT id FROM User WHERE id = ?`, 1); err == nil {
		t.Fatal("want cancelled error, got nil")
	}
	_ = auth.NewService(conn, t.TempDir())
}
func TestBusyTimeoutFiveSeconds(t *testing.T) {
	conn, err := db.Open(filepath.Join(t.TempDir(), "timeout.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	var timeout int
	if err := conn.QueryRow(`PRAGMA busy_timeout`).Scan(&timeout); err != nil {
		t.Fatal(err)
	}
	if timeout != 5000 {
		t.Fatalf("busy_timeout = %d, want 5000", timeout)
	}
	if _, err := conn.QueryContext(context.TODO(), `SELECT 1`); err != nil {
		t.Fatal(err)
	}
}
