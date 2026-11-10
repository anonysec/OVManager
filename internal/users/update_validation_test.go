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

func TestUpdateRejectsInvalidMaxLogins(t *testing.T) {
	conn, err := db.Open(filepath.Join(t.TempDir(), "users.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := conn.Exec(`CREATE TABLE User (
		id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, name TEXT UNIQUE, total BIGINT, used BIGINT,
		last_node_usage BIGINT DEFAULT 0, node_usage TEXT DEFAULT '{}', max_logins INTEGER DEFAULT 1,
		expiry_date TEXT, is_active INTEGER DEFAULT 1, last_online TEXT, tag TEXT);
CREATE TABLE Session (username TEXT, ip TEXT, created_at REAL);
CREATE TABLE Setting (id INTEGER PRIMARY KEY);
INSERT INTO User (id, uuid, name, max_logins, is_active, tag) VALUES (1, 'u1', 'alice', 3, 1, 'keep');`); err != nil {
		t.Fatal(err)
	}
	h := NewHandler(auth.NewService(conn, t.TempDir()))
	cases := []struct {
		body string
	}{
		{`{"max_logins":5000}`},
		{`{"max_logins":-1}`},
		{`{"max_logins":"abc"}`},
		{`{"total":"abc"}`},
		{`{"status":"yes"}`},
		{`{"tag":123}`},
		{`{"expiry_date":20260101}`},
	}
	for _, tc := range cases {
		req := httptest.NewRequest(http.MethodPut, "/users/u1", strings.NewReader(tc.body))
		req.SetPathValue("uuid", "u1")
		rec := httptest.NewRecorder()
		h.update(rec, req)
		if rec.Code != http.StatusUnprocessableEntity {
			t.Fatalf("body %s: status = %d, want 422 (body %s)", tc.body, rec.Code, rec.Body.String())
		}
		if !strings.Contains(rec.Body.String(), "detail") {
			t.Fatalf("body %s: expected validation error body, got %s", tc.body, rec.Body.String())
		}
	}
	var maxLogins int64
	if err := conn.QueryRow(`SELECT max_logins FROM User WHERE id = 1`).Scan(&maxLogins); err != nil {
		t.Fatal(err)
	}
	if maxLogins != 3 {
		t.Fatalf("max_logins mutated to %d by rejected updates", maxLogins)
	}
	var tag string
	if err := conn.QueryRow(`SELECT COALESCE(tag,'') FROM User WHERE id = 1`).Scan(&tag); err != nil {
		t.Fatal(err)
	}
	if tag != "keep" {
		t.Fatalf("tag mutated to %q by rejected updates", tag)
	}
	// A valid update still applies.
	req := httptest.NewRequest(http.MethodPut, "/users/u1", strings.NewReader(`{"max_logins":5}`))
	req.SetPathValue("uuid", "u1")
	rec := httptest.NewRecorder()
	h.update(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("valid update: status = %d, body %s", rec.Code, rec.Body.String())
	}
	if err := conn.QueryRow(`SELECT max_logins FROM User WHERE id = 1`).Scan(&maxLogins); err != nil {
		t.Fatal(err)
	}
	if maxLogins != 5 {
		t.Fatalf("valid update did not apply: max_logins = %d", maxLogins)
	}
}
