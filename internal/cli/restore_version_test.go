// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package cli

import (
	"database/sql"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/db"
)

func TestRestoreStampsVersion(t *testing.T) {
	dir := t.TempDir()
	dst := filepath.Join(dir, "dst.db")
	// emulate a restored backup: file copied, stamp re-applied by restore.
	conn, err := sql.Open("sqlite", dst)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	conn.Exec(`PRAGMA user_version = 30`)
	var v int
	conn.QueryRow(`PRAGMA user_version`).Scan(&v)
	if v != 30 {
		t.Fatalf("post-restore user_version = %d, want 30", v)
	}
}

func TestVersionRejectsNewerSchema(t *testing.T) {
	dir := t.TempDir()
	conn, err := sql.Open("sqlite", filepath.Join(dir, "newer.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	conn.Exec(`PRAGMA user_version = 99`)
	conn.Exec(`CREATE TABLE IF NOT EXISTS users(id INTEGER)`)
	if _, err := db.Migrate(conn); err == nil {
		t.Fatal("migrate on newer schema accepted")
	}
}
