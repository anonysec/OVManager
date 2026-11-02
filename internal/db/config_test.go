// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package db

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestOpenConfigSQLiteOnly(t *testing.T) {
	tmp := t.TempDir()
	dbPath := filepath.Join(tmp, "test.db")

	// 1. SQLite opens successfully
	cfg := Config{Path: dbPath}
	conn, err := OpenConfig(cfg)
	if err != nil {
		t.Fatalf("OpenConfig SQLite: %v", err)
	}
	defer conn.Close()
	if err := conn.Ping(); err != nil {
		t.Fatalf("Ping SQLite: %v", err)
	}

	// 2. Postgres is rejected with clear error
	pgCfg := Config{URL: "postgresql://user:pass@localhost:5432/ovm"}
	_, err = OpenConfig(pgCfg)
	if err == nil || !strings.Contains(err.Error(), "SQLite-only") {
		t.Fatalf("expected SQLite-only error on postgres, got: %v", err)
	}

	// 3. MySQL is rejected with clear error
	myCfg := Config{URL: "mysql://user:pass@localhost:3306/ovm"}
	_, err = OpenConfig(myCfg)
	if err == nil || !strings.Contains(err.Error(), "SQLite-only") {
		t.Fatalf("expected SQLite-only error on mysql, got: %v", err)
	}
}
