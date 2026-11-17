// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/db"
)

func TestSubURLFallbackIsTopLevel(t *testing.T) {
	conn, err := db.Open(filepath.Join(t.TempDir(), "sub.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	_, err = conn.Exec(`
CREATE TABLE Setting (id INTEGER PRIMARY KEY, urlpath VARCHAR DEFAULT 'dashboard', subscription_url_prefix VARCHAR, subscription_path VARCHAR DEFAULT 'sub');
INSERT INTO Setting (id, urlpath) VALUES (1, 'dashboard');
`)
	if err != nil {
		t.Fatal(err)
	}
	got := subURL(conn, "abc")
	want := "https://127.0.0.1:2095/sub/abc.txt"
	if got != want {
		t.Fatalf("subURL = %q, want %q", got, want)
	}
}
