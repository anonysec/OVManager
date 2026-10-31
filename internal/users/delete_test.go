package users

import (
	"errors"
	"fmt"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/db"
)

func TestConcurrentDeletesKeepOneUser(t *testing.T) {
	conn, err := db.Open(filepath.Join(t.TempDir(), "users.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := conn.Exec(`CREATE TABLE users (id INTEGER PRIMARY KEY, uuid TEXT UNIQUE);
CREATE TABLE user_traffic_daily (user_id INTEGER, bytes INTEGER);`); err != nil {
		t.Fatal(err)
	}
	h := NewHandler(auth.NewService(conn, t.TempDir()))
	for i := 0; i < 20; i++ {
		if _, err := conn.Exec(`DELETE FROM users; DELETE FROM user_traffic_daily;
INSERT INTO users (id, uuid) VALUES (1, 'a'), (2, 'b');
INSERT INTO user_traffic_daily (user_id, bytes) VALUES (1, 100), (2, 200);`); err != nil {
			t.Fatal(err)
		}
		start := make(chan struct{})
		done := make(chan error, 2)
		for id, uuid := range map[int64]string{1: "a", 2: "b"} {
			row := userRow{ID: id, UUID: uuid, Name: fmt.Sprint(id)}
			go func() {
				<-start
				_, err := h.deleteRow(row, false)
				done <- err
			}()
		}
		close(start)
		first, second := <-done, <-done
		if !((first == nil && errors.Is(second, errKeepLastUser)) ||
			(second == nil && errors.Is(first, errKeepLastUser))) {
			t.Fatalf("iteration %d: deletes returned %v and %v", i, first, second)
		}
		var users, daily int
		if err := conn.QueryRow(`SELECT COUNT(*) FROM users`).Scan(&users); err != nil {
			t.Fatal(err)
		}
		if err := conn.QueryRow(`SELECT COUNT(*) FROM user_traffic_daily`).Scan(&daily); err != nil {
			t.Fatal(err)
		}
		if users != 1 || daily != 1 {
			t.Fatalf("iteration %d: users=%d daily=%d, want 1 each", i, users, daily)
		}
	}
}

func TestFailedDeleteRollsBackUser(t *testing.T) {
	conn, err := db.Open(filepath.Join(t.TempDir(), "users.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	// Fail the user delete after deleting its history; both must roll back.
	if _, err := conn.Exec(`CREATE TABLE users (id INTEGER PRIMARY KEY, uuid TEXT);
CREATE TABLE user_traffic_daily (user_id INTEGER, bytes INTEGER);
INSERT INTO users VALUES (1, 'a'), (2, 'b');
INSERT INTO user_traffic_daily VALUES (1, 100);
CREATE TRIGGER refuse_delete BEFORE DELETE ON users BEGIN SELECT RAISE(ABORT, 'no'); END;`); err != nil {
		t.Fatal(err)
	}
	h := NewHandler(auth.NewService(conn, t.TempDir()))
	if _, err := h.deleteRow(userRow{ID: 1, UUID: "a"}, false); err == nil {
		t.Fatal("expected daily-history deletion to fail")
	}
	var count int
	if err := conn.QueryRow(`SELECT COUNT(*) FROM users`).Scan(&count); err != nil || count != 2 {
		t.Fatalf("users after rollback = %d, err=%v", count, err)
	}
	if err := conn.QueryRow(`SELECT COUNT(*) FROM user_traffic_daily`).Scan(&count); err != nil || count != 1 {
		t.Fatalf("history after rollback = %d, err=%v", count, err)
	}
}
