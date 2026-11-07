// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package tests

import (
	"database/sql"
	"testing"

	"github.com/anonysec/OVManager/go/internal/db"
)

// TestFreshSchemaMatchesMigratedSchema: a fresh install and an upgraded
// database must carry identical table_info shape (no silent drift).
func TestFreshSchemaMatchesMigratedSchema(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", "migrate-owner")
	t.Setenv("ADMIN_PASSWORD_HASH", "")
	t.Setenv("DEFAULT_USER", "user1")
	t.Setenv("URLPATH", "")
	fresh := newMigrateDB(t)
	if _, err := db.Migrate(fresh); err != nil {
		t.Fatalf("fresh migrate: %v", err)
	}
	migrated := newMigrateDB(t)
	migrated.Exec(`PRAGMA user_version = 0`)
	if _, err := db.Migrate(migrated); err != nil {
		t.Fatalf("migrated migrate: %v", err)
	}
	for _, table := range []string{"users", "admins", "sessions", "nodes", "settings", "settings_kv", "pending_user_revocations"} {
		freshCols := columnsOf(t, fresh, table)
		migratedCols := columnsOf(t, migrated, table)
		if len(freshCols) != len(migratedCols) {
			t.Fatalf("table %s: fresh %d cols vs migrated %d cols", table, len(freshCols), len(migratedCols))
		}
		for i, c := range freshCols {
			if c != migratedCols[i] {
				t.Fatalf("table %s col %d: fresh %q vs migrated %q", table, i, c, migratedCols[i])
			}
		}
	}
}

func columnsOf(t *testing.T, conn interface {
	Query(string, ...any) (*sql.Rows, error)
}, table string) []string {
	t.Helper()
	rows, err := conn.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var cid, notnull, pk int
		var name, ctype string
		var dflt sql.NullString
		if rows.Scan(&cid, &name, &ctype, &notnull, &dflt, &pk) == nil {
			out = append(out, name)
		}
	}
	return out
}
