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
	"strings"

	"github.com/anonysec/OVManager/go/internal/config"
)

// Backend identifies a supported database engine.
type Backend string

const (
	BackendSQLite   Backend = "sqlite"
	BackendPostgres Backend = "postgres"
	BackendMySQL    Backend = "mysql"
)

// Config describes how to open a database. URL uses PasarGuard-style schemes
// (sqlite:///path, postgresql://..., mysql://...); an empty URL means "use
// Path as a SQLite file", preserving the legacy behaviour.
type Config struct {
	URL      string // PasarGuard-style connection URL (SQLALCHEMY_DATABASE_URL)
	Path     string // SQLite file path used when URL is empty
	PoolSize int
}

// ConfigFromEnv builds a Config from environment variables, following
// PasarGuard precedence: process env wins over .env (handled by callers via
// envOrFile where available). Recognised variables, in priority order:
//
//	DATABASE_URL / SQLALCHEMY_DATABASE_URL / DB_URL   connection URL
//	DATA_DIR                                         SQLite directory fallback
//	DB_PATH                                          explicit SQLite file
//
// envOrFileDB reads a key from process env, falling back to the panel .env
// file (which wins for forcing values, per PasarGuard precedence override).
func ConfigFromEnv() Config {
	cfg := Config{PoolSize: 5}
	if v := config.EnvOrFile("POOL_SIZE", ""); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			cfg.PoolSize = n
		}
	}
	if v := config.EnvOrFile("DB_POOL_SIZE", ""); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			cfg.PoolSize = n
		}
	}
	for _, key := range []string{"DATABASE_URL", "SQLALCHEMY_DATABASE_URL", "DB_URL"} {
		if v := config.EnvOrFile(key, ""); v != "" {
			cfg.URL = v
			return cfg
		}
	}
	if p := config.EnvOrFile("DB_PATH", ""); p != "" {
		cfg.Path = p
		return cfg
	}
	dir := config.EnvOrFile("DATA_DIR", "data")
	cfg.Path = filepath.Join(dir, "ovmanager.db")
	return cfg
}

// Backend returns the engine implied by cfg.
func (c Config) Backend() Backend {
	u := strings.ToLower(strings.TrimSpace(c.URL))
	switch {
	case u == "":
		return BackendSQLite
	case strings.HasPrefix(u, "sqlite"):
		return BackendSQLite
	case strings.HasPrefix(u, "postgres"), strings.HasPrefix(u, "postgresql"):
		return BackendPostgres
	case strings.HasPrefix(u, "mysql"), strings.HasPrefix(u, "mariadb"):
		return BackendMySQL
	}
	return BackendSQLite
}

// OpenConfig opens a database from cfg. Only SQLite is supported;
// Postgres and MySQL configurations return a clear error.
func OpenConfig(cfg Config) (*sql.DB, error) {
	b := cfg.Backend()
	if b != BackendSQLite {
		return nil, fmt.Errorf("database engine %q is not supported: OVManager is SQLite-only", b)
	}
	path := cfg.Path
	if path == "" {
		path = sqlitePathFromURL(cfg.URL)
	}
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

// sqlitePathFromURL extracts a filesystem path from a sqlite:/// URL,
// mirroring SQLAlchemy's handling (sqlite:///relative, sqlite:////absolute).
func sqlitePathFromURL(u string) string {
	u = strings.TrimSpace(u)
	if u == "" {
		return ""
	}
	u = strings.TrimPrefix(u, "sqlite+aiosqlite:///")
	u = strings.TrimPrefix(u, "sqlite:///")
	u = strings.TrimPrefix(u, "sqlite://")
	if u == "" {
		return ""
	}
	// sqlite:////abs -> /abs (already has leading slash after trim of 3)
	if !filepath.IsAbs(u) && strings.HasPrefix(u, "/") {
		return u
	}
	return u
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

// SQLitePathFromURL exports sqlitePathFromURL for callers that resolve the
// effective database file from a connection URL.
func SQLitePathFromURL(u string) string { return sqlitePathFromURL(u) }
