package users

import (
	"database/sql"
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
	if _, err := conn.Exec(`CREATE TABLE User (
		id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, name TEXT UNIQUE, total BIGINT, used BIGINT,
		last_node_usage BIGINT DEFAULT 0, node_usage TEXT DEFAULT '{}', max_logins INTEGER DEFAULT 1,
		expiry_date TEXT, is_active INTEGER DEFAULT 1, last_online TEXT, tag TEXT);
	CREATE TABLE Session (username TEXT, ip TEXT, created_at REAL);
	CREATE TABLE Setting (id INTEGER PRIMARY KEY);
	CREATE TABLE UserTrafficDaily (user_id INTEGER, bytes INTEGER);
	CREATE TABLE deleted_users (uuid TEXT PRIMARY KEY, snap_json TEXT NOT NULL, deleted_at REAL NOT NULL, expires_at REAL NOT NULL);
	INSERT INTO User (id, uuid, name, max_logins, is_active, tag) VALUES (1, 'u1', 'alice', 3, 1, 'keepme'), (2, 'u2', 'bob', 3, 1, '');`); err != nil {
		t.Fatal(err)
	}
	return NewHandler(auth.NewService(conn, t.TempDir()))
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

// total IS NULL means unlimited. Extending by bytes must leave it NULL,
// not turn the account into a 100-byte quota.
func TestExtendKeepsUnlimited(t *testing.T) {
	h := fixTestDB(t)
	req := httptest.NewRequest(http.MethodPut, "/users/u1/extend", strings.NewReader(`{"bytes":100}`))
	req.SetPathValue("uuid", "u1")
	rec := httptest.NewRecorder()
	h.extend(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body %s", rec.Code, rec.Body.String())
	}
	var total sql.NullInt64
	if err := h.Svc.DB().QueryRow(`SELECT total FROM User WHERE uuid = 'u1'`).Scan(&total); err != nil {
		t.Fatal(err)
	}
	if total.Valid {
		t.Fatalf("total = %d, want NULL (unlimited)", total.Int64)
	}
}
