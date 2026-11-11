// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT
//
// Database configuration. SQLite is the dedicated database engine for
// the single-process deployment.

package db

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"strconv"

	"github.com/anonysec/OVManager/internal/config"
)

// Config describes how to open a database.
type Config struct {
	Path     string // SQLite file path
	PoolSize int
}

// ConfigFromEnv builds a Config from environment variables:
//
//	DB_PATH                                          explicit SQLite file
//	DATA_DIR                                         SQLite directory fallback
//	DB_POOL_SIZE                                     connection pool size
//
// DB_PATH wins over DATA_DIR; DATA_DIR defaults to "data".
func ConfigFromEnv() Config {
	cfg := Config{PoolSize: 5}
	if v := config.EnvOrFile("DbPoolSize", ""); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			cfg.PoolSize = n
		}
	}
	if p := config.EnvOrFile("DbPath", ""); p != "" {
		cfg.Path = p
		return cfg
	}
	dir := config.EnvOrFile("DataDir", "data")
	cfg.Path = filepath.Join(dir, "app.db")
	return cfg
}

// OpenConfig opens a database from cfg.
func OpenConfig(cfg Config) (*sql.DB, error) {
	path := cfg.Path
	if path == "" {
		path = DefaultPath
	}
	conn, err := Open(path)
	if err != nil {
		return nil, err
	}
	if cfg.PoolSize > 0 {
		conn.SetMaxOpenConns(cfg.PoolSize)
		conn.SetMaxIdleConns(cfg.PoolSize)
	}
	return conn, nil
}

// Open keeps the legacy signature (SQLite file path) so existing callers
// refuseOrphanedLegacyDatabase stops a 2.0.0 build from starting beside a
// pre-2.0.0 database. Creating a fresh app.db there would look healthy while
// every user, node and setting stayed in the old file.
func refuseOrphanedLegacyDatabase(path string) error {
	if filepath.Base(path) != "app.db" {
		return nil
	}
	if _, err := os.Stat(path); err == nil {
		return nil
	}
	legacy := filepath.Join(filepath.Dir(path), "ovmanager.db")
	if _, err := os.Stat(legacy); err == nil {
		return fmt.Errorf("found %s but this build uses %s; 2.0.0 cannot upgrade a pre-2.0.0 database — move it aside and start fresh", legacy, path)
	}
	return nil
}

// keep working while the codebase migrates to OpenConfig.
func Open(path string) (*sql.DB, error) {
	if path == "" {
		path = DefaultPath
	}
	if err := refuseOrphanedLegacyDatabase(path); err != nil {
		return nil, err
	}
	conn, err := sql.Open("sqlite", "file:"+path+dsnPragmas)
	if err != nil {
		return nil, fmt.Errorf("open sqlite %s: %w", path, err)
	}
	if err := conn.Ping(); err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("ping sqlite %s: %w", path, err)
	}
	_ = os.Chmod(path, 0o600)
	return conn, err
}
