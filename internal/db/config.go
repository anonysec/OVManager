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
	if v := config.EnvOrFile("DB_POOL_SIZE", ""); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			cfg.PoolSize = n
		}
	}
	if p := config.EnvOrFile("DB_PATH", ""); p != "" {
		cfg.Path = p
		return cfg
	}
	dir := config.EnvOrFile("DATA_DIR", "data")
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
// keep working while the codebase migrates to OpenConfig.
func Open(path string) (*sql.DB, error) {
	if path == "" {
		path = DefaultPath
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
