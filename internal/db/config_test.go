// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package db

import (
	"path/filepath"
	"testing"
)

func TestOpenConfigSQLiteOnly(t *testing.T) {
	tmp := t.TempDir()
	dbPath := filepath.Join(tmp, "test.db")

	cfg := Config{Path: dbPath}
	conn, err := OpenConfig(cfg)
	if err != nil {
		t.Fatalf("OpenConfig SQLite: %v", err)
	}
	defer conn.Close()
	if err := conn.Ping(); err != nil {
		t.Fatalf("Ping SQLite: %v", err)
	}
}

func TestConfigFromEnv(t *testing.T) {
	t.Setenv("DB_PATH", "/tmp/explicit.db")
	t.Setenv("DATA_DIR", "/tmp/fallback")
	t.Setenv("DB_POOL_SIZE", "9")
	cfg := ConfigFromEnv()
	if cfg.Path != "/tmp/explicit.db" {
		t.Fatalf("Path = %q, want /tmp/explicit.db", cfg.Path)
	}
	if cfg.PoolSize != 9 {
		t.Fatalf("PoolSize = %d, want 9", cfg.PoolSize)
	}
}
