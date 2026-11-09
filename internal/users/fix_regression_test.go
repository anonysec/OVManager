package users

import (
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/db"
)

func fixTestDB(t *testing.T) *Handler {
	t.Helper()
	conn, err := db.Open(filepath.Join(t.TempDir(), "users.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(`CREATE TABLE users (
		id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, name TEXT UNIQUE, total BIGINT, used BIGINT,
		last_node_usage BIGINT DEFAULT 0, node_usage TEXT DEFAULT '{}', max_logins INTEGER DEFAULT 1,
		expiry_date TEXT, is_active INTEGER DEFAULT 1, last_online TEXT, tag TEXT);
	CREATE TABLE sessions (username TEXT, ip TEXT, created_at REAL);
	CREATE TABLE settings (id INTEGER PRIMARY KEY);
	CREATE TABLE user_traffic_daily (user_id INTEGER, bytes INTEGER);
	CREATE TABLE deleted_users (uuid TEXT PRIMARY KEY, snap_json TEXT NOT NULL, deleted_at REAL NOT NULL, expires_at REAL NOT NULL);
	INSERT INTO users (id, uuid, name, max_logins, is_active, tag) VALUES (1, 'u1', 'alice', 3, 1, 'keepme'), (2, 'u2', 'bob', 3, 1, '');`); err != nil {
		t.Fatal(err)
	}
	return NewHandler(auth.NewService(conn, t.TempDir()))
}

func TestDeleteWritesUndoSnapshotAtomic(t *testing.T) {
	h := fixTestDB(t)
	row, ok := h.byUUID("u1")
	if !ok {
		t.Fatal("row missing")
	}
	if _, err := h.deleteRow(row, false); err != nil {
		t.Fatal(err)
	}
	var cnt int
	if err := h.Svc.DB().QueryRow(`SELECT COUNT(*) FROM deleted_users WHERE uuid = 'u1'`).Scan(&cnt); err != nil {
		t.Fatal(err)
	}
	if cnt != 1 {
		t.Fatalf("deleted_users count = %d, want 1", cnt)
	}
}

func TestExtendRejectsNegative(t *testing.T) {
	h := fixTestDB(t)
	for _, body := range []string{`{"days":-5}`, `{"bytes":-100}`} {
		req := httptest.NewRequest(http.MethodPut, "/users/u1/extend", strings.NewReader(body))
		req.SetPathValue("uuid", "u1")
		rec := httptest.NewRecorder()
		h.extend(rec, req)
		if rec.Code != http.StatusUnprocessableEntity {
			t.Fatalf("body %s: status = %d, want 422", body, rec.Code)
		}
	}
}

func TestRestoreKeepsTag(t *testing.T) {
	h := fixTestDB(t)
	row, _ := h.byUUID("u1")
	if _, err := h.deleteRow(row, false); err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, "/users/u1/restore", nil)
	req.SetPathValue("uuid", "u1")
	rec := httptest.NewRecorder()
	h.restore(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("restore status = %d, body %s", rec.Code, rec.Body.String())
	}
	var tag string
	if err := h.Svc.DB().QueryRow(`SELECT COALESCE(tag,'') FROM users WHERE uuid = 'u1'`).Scan(&tag); err != nil {
		t.Fatal(err)
	}
	if tag != "keepme" {
		t.Fatalf("restored tag = %q, want keepme", tag)
	}
}
